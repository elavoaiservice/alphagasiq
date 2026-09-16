"""The worker must read GUI-managed configuration, not only `.env`.

The worker process never applied the DB config overlay, so every setting saved in
the admin Configuration page was invisible to the one process that actually does the
ingesting. In the deployed environment that meant an `EIA_API_KEY` saved in the GUI
left the worker's provider reporting `not_configured` (EIA skipped entirely, with no
feed event to show for it), while a stale `.env` `USE_MOCK_MARKET_DATA=true` kept the
worker writing simulated prices regardless of what the GUI said — the API process and
the worker disagreed about what was configured.
"""
from __future__ import annotations

import pytest

from api_app import config_store


@pytest.fixture
def state_module():
    from api_app import state as sm

    sm.reset_app_state()
    yield sm
    sm.reset_app_state()


# ── the fingerprint used to notice a config change ────────────────────────────

@pytest.mark.asyncio
async def test_fingerprint_is_stable_for_unchanged_config(state_module):
    app_state = await state_module.get_app_state()
    sf = app_state.repo.session_factory
    assert await config_store.fingerprint(sf) == await config_store.fingerprint(sf)


@pytest.mark.asyncio
async def test_fingerprint_changes_when_a_value_is_saved(state_module):
    app_state = await state_module.get_app_state()
    sf = app_state.repo.session_factory

    before = await config_store.fingerprint(sf)
    await config_store.set_value(sf, "LOG_LEVEL", "DEBUG")
    after = await config_store.fingerprint(sf)

    assert before != after


@pytest.mark.asyncio
async def test_fingerprint_changes_when_a_value_is_edited_again(state_module):
    app_state = await state_module.get_app_state()
    sf = app_state.repo.session_factory

    await config_store.set_value(sf, "LOG_LEVEL", "DEBUG")
    first = await config_store.fingerprint(sf)
    await config_store.set_value(sf, "LOG_LEVEL", "INFO")
    second = await config_store.fingerprint(sf)

    assert first != second


@pytest.mark.asyncio
async def test_fingerprint_does_not_decrypt_secrets(state_module, monkeypatch):
    """Noticing that config changed must not require a plaintext secret."""
    app_state = await state_module.get_app_state()
    sf = app_state.repo.session_factory
    await config_store.set_value(sf, "EIA_API_KEY", "super-secret")

    def _boom(_value):
        raise AssertionError("fingerprint must not decrypt stored values")

    monkeypatch.setattr(config_store, "_decrypt", _boom)
    assert await config_store.fingerprint(sf)  # non-empty, no decryption


# ── the worker applies the overlay ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_helper_returns_empty_string_when_config_unreadable(state_module):
    """A config-table hiccup must never stop the worker loop."""
    from api_app import worker

    class _Broken:
        class repo:
            session_factory = None

    async def _raise(_sf):
        raise RuntimeError("db down")

    import api_app.config_store as cs

    original = cs.fingerprint
    cs.fingerprint = _raise
    try:
        assert await worker._config_fingerprint(_Broken()) == ""
    finally:
        cs.fingerprint = original


@pytest.mark.asyncio
async def test_overlay_makes_a_gui_saved_key_visible_to_settings(state_module, monkeypatch):
    """The actual EIA failure mode: a key saved in the GUI has to reach
    `get_settings()` in this process, or the provider reports not_configured."""
    import os

    from config import get_settings

    app_state = await state_module.get_app_state()
    sf = app_state.repo.session_factory

    monkeypatch.delenv("EIA_API_KEY", raising=False)
    get_settings.cache_clear()
    assert not get_settings().eia_api_key

    await config_store.set_value(sf, "EIA_API_KEY", "key-from-the-gui")
    await config_store.apply_overlay(sf)
    try:
        assert get_settings().eia_api_key == "key-from-the-gui"
    finally:
        os.environ.pop("EIA_API_KEY", None)
        get_settings.cache_clear()
