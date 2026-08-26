"""Connector interfaces defined in docs/data-sources.md that are not yet implemented.

Each is registered as a `NotImplementedProvider` so it shows up (honestly, as
`not_configured`) in `/system/providers` rather than being silently absent. Implementing
one of these is a matter of subclassing `BaseDataProvider` the same way
`services/data/data_service/providers/eia.py` does and swapping it in
`registry.py::build_default_registry` — as `iso_rto.py` and `sec_edgar.py` now do for
`ISO_RTO_PUBLIC` and `SEC_EDGAR` (removed from this stub list below).

`FERC_PUBLIC` and `PIPELINE_BULLETIN_BOARD` deliberately remain stubs rather than a
best-guess implementation: FERC eLibrary and per-pipeline electronic bulletin boards
don't expose a single stable, well-documented public JSON API the way EIA/NOAA/SEC
EDGAR do (eLibrary is a document-search portal; EBB data is scattered across dozens of
pipeline operators' own bespoke web interfaces, no common schema). A connector against
either would need per-pipeline scraping this codebase has no way to verify correct in
this environment (no live network access to confirm shapes) — an honest
`not_configured` stub is preferable to a plausible-looking but unverified integration.
"""

from data_sdk import NotImplementedProvider
from schemas import DataClassification

FERC_PUBLIC = NotImplementedProvider("ferc_public", DataClassification.PUBLIC)
PIPELINE_BULLETIN_BOARD = NotImplementedProvider("pipeline_bulletin_board", DataClassification.PUBLIC)
LICENSED_NEWS = NotImplementedProvider("licensed_news", DataClassification.LICENSED)
CME_LIVE = NotImplementedProvider("cme_live", DataClassification.LICENSED)
ICE_LIVE = NotImplementedProvider("ice_live", DataClassification.LICENSED)

ALL_STUBS = [
    FERC_PUBLIC,
    PIPELINE_BULLETIN_BOARD,
    LICENSED_NEWS,
    CME_LIVE,
    ICE_LIVE,
]
