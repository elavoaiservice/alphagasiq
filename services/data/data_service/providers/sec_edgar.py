from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

SEC_EDGAR_BASE_URL = "https://data.sec.gov"

# Natural-gas-relevant public companies this connector tracks filings for, by CIK
# (10-digit, zero-padded) -- major LNG/E&P/pipeline names. A real deployment would
# make this list configurable rather than hardcoded.
TRACKED_COMPANIES: dict[str, str] = {
    "0000895729": "Cheniere Energy Inc",
    "0001513761": "Williams Companies Inc",
    "0001513818": "Kinder Morgan Inc",
    "0000033213": "EQT Corporation",
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
                resp = await client.get(f"{SEC_EDGAR_BASE_URL}/submissions/CIK{cik}.json")
                resp.raise_for_status()
                drafts.extend(self.normalize({"cik": cik, "raw": resp.json()}))
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
