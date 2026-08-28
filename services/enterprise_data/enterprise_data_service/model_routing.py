"""`ModelRoutingEngine` (docs/alpha-intelligence.md section 11.1, Milestone 9):
decides whether content of a given `EnterpriseDataClassification` may be sent to
an external LLM provider for a given organization -- the `ALLOW_EXTERNAL_LLM_
PROCESSING` gate the tenant-isolation retrofit calls for. A pure function, zero
I/O, exhaustively unit-testable -- the same design philosophy as
`risk_service.governor.RiskGovernor` and every other Alpha* engine in this
codebase.

`ChatAgent._enterprise_data_query` (`apps/api/api_app/chat_agent.py`) is the live caller:
it evaluates every dataset classification involved in a request, withholds any blocked
dataset's content from the facts handed to the LLM, and also wraps the final
prose-synthesis call itself in `agent_sdk.llm.PolicyGatedLLMProvider` -- gated by the
combined decision across every involved dataset (blocked if any one is) -- so a blocked
classification keeps that summarization step off an external LLM entirely, not just its
raw content out of the prompt text. No agent (as opposed to chat tool) call site threads
a `data_classification` through this engine yet, since no agent consumes classified
enterprise data in its prompts today.
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas import EnterpriseDataClassification, ModelRoutingPolicy

# Provisional default posture (revisit once real customer usage exists, same
# "documented judgment call, not derived from data" discipline as AlphaSignal's
# materiality weights): classifications that never touched customer-provided
# proprietary data default to allowed; every CUSTOMER_* tier defaults to
# *blocked* absent an explicit organization opt-in policy -- conservative-by-
# default rather than conservative-by-configuration.
_DEFAULT_ALLOWED_CLASSIFICATIONS = frozenset(
    {
        EnterpriseDataClassification.PUBLIC,
        EnterpriseDataClassification.LICENSED_MARKET_DATA,
        EnterpriseDataClassification.ALPHAGASIQ_PROPRIETARY,
        EnterpriseDataClassification.SIMULATED,
    }
)


@dataclass
class RoutingDecision:
    allowed: bool
    reason: str
    allowed_provider: str | None = None
    allowed_region: str | None = None
    logging_allowed: bool = True


class ModelRoutingEngine:
    def evaluate(
        self,
        *,
        data_classification: EnterpriseDataClassification,
        policies: list[ModelRoutingPolicy],
        organization_id: str | None,
    ) -> RoutingDecision:
        """`policies` should be every policy visible to `organization_id`
        (its own overrides plus the platform defaults) -- exactly what
        `Repository.list_model_routing_policies(organization_id=...)` returns.
        An organization-scoped policy for `data_classification` always wins
        over a platform-default one for the same classification."""
        org_policy = next(
            (
                p
                for p in policies
                if p.organization_id == organization_id and p.data_classification == data_classification
            ),
            None,
        )
        if org_policy is not None:
            return self._decision_from_policy(org_policy, source="organization override")

        platform_policy = next(
            (p for p in policies if p.organization_id is None and p.data_classification == data_classification),
            None,
        )
        if platform_policy is not None:
            return self._decision_from_policy(platform_policy, source="platform default")

        if data_classification in _DEFAULT_ALLOWED_CLASSIFICATIONS:
            return RoutingDecision(allowed=True, reason=f"no policy configured for {data_classification.value}; built-in default is allow")
        return RoutingDecision(
            allowed=False,
            reason=f"no policy configured for {data_classification.value}; customer-tier classifications default to blocked",
        )

    @staticmethod
    def _decision_from_policy(policy: ModelRoutingPolicy, *, source: str) -> RoutingDecision:
        return RoutingDecision(
            allowed=policy.allow_external_llm_processing,
            reason=f"{source} policy for {policy.data_classification.value}",
            allowed_provider=policy.allowed_provider,
            allowed_region=policy.allowed_region,
            logging_allowed=policy.logging_allowed,
        )
