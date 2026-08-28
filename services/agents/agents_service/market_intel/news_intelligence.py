from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef, NewsEvent
from schemas.observation import ObservationDraft


class NewsIntelligenceAgent(BaseAgent):
    """Market Intelligence Team: ingest -> dedupe -> classify -> structured NewsEvent.

    Consumes raw news `ObservationDraft`s (category=NEWS_EVENT) from any registered
    news provider (mock or licensed/RSS) and produces structured, citation-preserving
    `NewsEvent` objects. Event-type/impact classification is currently a deterministic
    mapping off provider metadata (see docs/data-sources.md); an LLM pass adds the
    narrative summary but never invents the structured fields.
    """

    agent_id = "market_intel.news_intelligence.v1"
    agent_name = "News Intelligence Agent"
    agent_type = AgentType.NEWS_INTELLIGENCE
    version = "0.1.0"

    async def _execute(self, *, raw_items: list[ObservationDraft]) -> AgentOutcome:
        if not raw_items:
            return AgentOutcome(status=AgentStatus.SKIPPED, reasoning_summary="No news items to process.")

        seen_headlines: set[str] = set()
        events: list[NewsEvent] = []
        for item in raw_items:
            headline = item.metadata.get("headline", "")
            if not headline or headline in seen_headlines:
                continue
            seen_headlines.add(headline)

            magnitude = float(item.value)
            bullish_bearish = item.metadata.get("bullish_bearish", "NEUTRAL")
            supply_impact = -magnitude * 2 if bullish_bearish == "BULLISH" else magnitude * 2 if bullish_bearish == "BEARISH" else 0.0

            events.append(
                NewsEvent(
                    headline=headline,
                    source=item.source,
                    source_url=item.metadata.get("source_url", ""),
                    published_at=item.publication_time,
                    event_type=item.sub_category or "other",
                    entities=[],
                    locations=item.metadata.get("locations", [item.geography] if item.geography else []),
                    summary=headline,
                    supply_impact_bcf_day=round(supply_impact, 2),
                    demand_impact_bcf_day=0.0,
                    expected_duration=None,
                    affected_markets=["Henry Hub"],
                    bullish_bearish=bullish_bearish,
                    magnitude=round(magnitude, 2),
                    confidence=0.6 if item.source_type == DataClassification.SIMULATED else 0.75,
                    citations=[item.metadata.get("source_url", item.source)],
                )
            )

        top = sorted(events, key=lambda e: e.magnitude, reverse=True)[:3]
        prompt = "Summarize the most market-moving of these headlines in one sentence: " + "; ".join(
            e.headline for e in top
        )
        llm_response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )

        return AgentOutcome(
            outputs={"events": [e.model_dump(mode="json") for e in events]},
            reasoning_summary=f"Classified {len(events)} distinct news events. {llm_response.content}",
            confidence=0.65,
            tools=["news_intelligence.classify"],
            data_sources=[
                DataSourceRef(provider_id=item.source.lower(), classification=item.source_type)
                for item in raw_items
            ][:5],
            citations=[Citation(source=e.source, reference=e.source_url or e.headline, publication_time=e.published_at, classification=DataClassification.SIMULATED) for e in top],
        )
