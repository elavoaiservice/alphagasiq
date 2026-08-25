"""Connector interfaces defined in docs/data-sources.md that are not yet implemented.

Each is registered as a `NotImplementedProvider` so it shows up (honestly, as
`not_configured`) in `/system/providers` rather than being silently absent. Implementing
one of these is a matter of subclassing `BaseDataProvider` the same way
`services/data/data_service/providers/eia.py` does and swapping it in
`registry.py::build_default_registry`.
"""

from data_sdk import NotImplementedProvider
from schemas import DataClassification

FERC_PUBLIC = NotImplementedProvider("ferc_public", DataClassification.PUBLIC)
PIPELINE_BULLETIN_BOARD = NotImplementedProvider("pipeline_bulletin_board", DataClassification.PUBLIC)
ISO_RTO_PUBLIC = NotImplementedProvider("iso_rto_public", DataClassification.PUBLIC)
SEC_EDGAR = NotImplementedProvider("sec_edgar", DataClassification.PUBLIC)
LICENSED_NEWS = NotImplementedProvider("licensed_news", DataClassification.LICENSED)
CME_LIVE = NotImplementedProvider("cme_live", DataClassification.LICENSED)
ICE_LIVE = NotImplementedProvider("ice_live", DataClassification.LICENSED)

ALL_STUBS = [
    FERC_PUBLIC,
    PIPELINE_BULLETIN_BOARD,
    ISO_RTO_PUBLIC,
    SEC_EDGAR,
    LICENSED_NEWS,
    CME_LIVE,
    ICE_LIVE,
]
