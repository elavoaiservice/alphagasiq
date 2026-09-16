from __future__ import annotations

import logging

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

SEC_EDGAR_BASE_URL = "https://data.sec.gov"

logger = logging.getLogger("alphagasiq.sec_edgar")


def _names_match(expected: str, actual: str) -> bool:
    """Loose company-name comparison, for catching a CIK that points at the wrong
    company. SEC's own casing and suffixes vary ("EQT Corp" vs "EQT Corporation",
    "WILLIAMS COMPANIES, INC."), so this compares the leading significant word
    rather than demanding an exact match — enough to catch Norwegian Cruise Line
    sitting where Williams should be, without rejecting a legitimate rename."""
    def key(name: str) -> str:
        cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in name.lower())
        for noise in ("inc", "corp", "corporation", "company", "companies", "lp", "ltd", "holdings", "the"):
            cleaned = cleaned.replace(f" {noise} ", " ")
        words = cleaned.split()
        return words[0] if words else ""

    return key(expected) == key(actual)

# Natural-gas-relevant public companies this connector tracks filings for, by CIK
# (10-digit, zero-padded) -- major LNG/E&P/pipeline names. A real deployment would
# make this list configurable rather than hardcoded.
#
# Every CIK below was verified against SEC's own registry
# (https://www.sec.gov/files/company_tickers.json) on 2026-09-16. Three of the four
# original entries were wrong, and only one of them failed loudly: Cheniere's CIK
# 404'd, while "Williams Companies" actually resolved to Norwegian Cruise Line
# Holdings and "Kinder Morgan" to Aravive, a biotech. The connector was ingesting
# cruise-line and pharmaceutical filings into a natural-gas platform under confident
# pipeline-operator labels. Never hand-write a CIK -- look it up in company_tickers.json
# and check the `name` that comes back from /submissions matches what you expect.
TRACKED_COMPANIES: dict[str, str] = {
    "0000003570": "Cheniere Energy, Inc.",       # LNG
    "0000107263": "Williams Companies, Inc.",    # WMB
    "0001506307": "Kinder Morgan, Inc.",         # KMI
    "0000033213": "EQT Corp",                    # EQT
    "0001039684": "ONEOK, Inc.",                 # OKE
    "0001276187": "Energy Transfer LP",          # ET
}

# 8-K (material events), 10-K/10-Q (periodic financials) are the filing types most
# likely to carry a genuine trading signal (outage/guidance/M&A disclosures); EDGAR
# also returns routine forms (3/4/5, S-8, etc.) this connector isn't trying to surface.
_RELEVANT_FORMS = {"8-K", "10-K", "10-Q"}

# Licensing metadata (spec §31), matching eia.py/noaa.py's identical public-domain
# government-data posture -- SEC filings are public record, freely redistributable.
_PUBLIC_GOV_DATA_LICENSE: dict[str, Any] = {
    "license_type": "PUBLIC_DOMAIN_GOVERNMENT_DATA",
    "public_or_commercial": "PUBLIC",
    "redistribution_allowed": True,
    "ai_processing_allowed": True,
}


class SECEdgarProvider(BaseDataProvider):
    """SEC EDGAR company-filings API. PUBLIC data, no API key required -- SEC's fair-
    access policy does require a descriptive `User-Agent` identifying the requester and
    a contact method (https://www.sec.gov/os/webmaster-faq#developers), sent via
    `contact_email`; requests without one risk being rate-limited/blocked by SEC.

    Docs: https://www.sec.gov/edgar/sec-api-documentation (the `submissions` endpoint).
    Surfaces recent 8-K/10-K/10-Q filings for a tracked list of natural-gas-relevant
    public companies as `CORPORATE_FILING` observations -- an unscheduled 8-K from a
    major LNG exporter or pipeline operator is exactly the kind of signal the News
    Intelligence team should be able to pick up on, the same way it already picks up
    RSS headlines.
    """

    provider_id = "sec_edgar"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 24 * 3600  # filings post intermittently, at most a few times/day
    license_type = _PUBLIC_GOV_DATA_LICENSE["license_type"]
    public_or_commercial = _PUBLIC_GOV_DATA_LICENSE["public_or_commercial"]
    redistribution_allowed = _PUBLIC_GOV_DATA_LICENSE["redistribution_allowed"]
    ai_processing_allowed = _PUBLIC_GOV_DATA_LICENSE["ai_processing_allowed"]

    def __init__(self, contact_email: str | None, client: httpx.AsyncClient | None = None):
        self.contact_email = contact_email
        self._client = client

    def _headers(self) -> dict[str, str]:
        contact = self.contact_email or "dev@alphagasiq.local"
        return {"User-Agent": f"AlphaGasIQ ({contact})", "Accept": "application/json"}

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        ciks = request.extra.get("ciks") or list(TRACKED_COMPANIES)
        drafts: list[ObservationDraft] = []
        async with (self._client or httpx.AsyncClient(headers=self._headers())) as client:
            for cik in ciks:
                # Per-CIK isolation: one delisted or mistyped identifier used to
                # abort the whole batch, so a single bad entry meant zero filings
                # from any company.
                try:
                    resp = await client.get(f"{SEC_EDGAR_BASE_URL}/submissions/CIK{cik}.json")
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception:
                    logger.warning("SEC EDGAR lookup failed for CIK%s; skipping", cik, exc_info=True)
                    continue

                # A wrong-but-valid CIK is the dangerous case: it returns 200 with a
                # different company's filings, which then flow in under the label we
                # expected. Two of the four original entries did exactly that.
                expected = TRACKED_COMPANIES.get(cik)
                actual = payload.get("name")
                if expected and actual and not _names_match(expected, actual):
                    logger.error(
                        "SEC EDGAR CIK%s is %r, not %r — refusing to ingest filings under the "
                        "wrong company. Verify the CIK in company_tickers.json.",
                        cik, actual, expected,
                    )
                    continue

                drafts.extend(self.normalize({"cik": cik, "raw": payload}))
        return drafts

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        cik: str = raw["cik"]
        payload: dict[str, Any] = raw["raw"]
        company_name = payload.get("name") or TRACKED_COMPANIES.get(cik, cik)
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])
        now = datetime.now(timezone.utc)

        drafts: list[ObservationDraft] = []
        for i, form in enumerate(forms):
            if form not in _RELEVANT_FORMS:
                continue
            filing_date = filing_dates[i] if i < len(filing_dates) else None
            if not filing_date:
                continue
            accession = accession_numbers[i] if i < len(accession_numbers) else None
            primary_doc = primary_documents[i] if i < len(primary_documents) else None
            filing_url = (
                f"{SEC_EDGAR_BASE_URL}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary_doc}"
                if accession and primary_doc
                else f"{SEC_EDGAR_BASE_URL}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            )
            drafts.append(
                ObservationDraft(
                    source="SEC_EDGAR",
                    source_type=self.classification,
                    series_id=f"SEC.FILING.{cik}",
                    commodity="NATURAL_GAS",
                    category="CORPORATE_FILING",
                    sub_category=form,
                    value=1.0,
                    unit="FILING_COUNT",
                    observation_time=datetime.strptime(filing_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
                    publication_time=now,
                    metadata={
                        "company_name": company_name,
                        "cik": cik,
                        "form": form,
                        "accession_number": accession,
                    },
                    lineage=Lineage(source_url=filing_url),
                    **_PUBLIC_GOV_DATA_LICENSE,
                )
            )
        return drafts
