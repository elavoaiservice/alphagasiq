import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Tests must never touch the dev-mode file-based sqlite DB (`alphagasiq_dev.db`) that
# `config.Settings.database_url` defaults to for `uvicorn --reload` runs — that would
# leak state between test runs and between tests and a locally running dev server.
# `:memory:` sqlite plus `packages/db/db/engine.py`'s `StaticPool` gives every
# `AppState()` instance (one per test, via the `client` fixture's `reset_app_state()`)
# its own fully isolated database. Must be set before `config.get_settings()` (which
# is `@lru_cache`'d) is imported/called anywhere.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
