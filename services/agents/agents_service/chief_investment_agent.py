from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent
from schemas import AgentType, InvestmentCommitteeDecision, RecommendedAction, RiskVerdict


class ChiefInvestmentAgent(BaseAgent):
    """Receives research and AI-Investment-Committee-reviewed trade ideas and decides
    whether to forward a trade for human review.

    CRITICAL: this agent CANNOT override the Risk Governor. `decide()` requires a
    `risk_verdict` and will never forward a trade whose verdict is not `ALLOW` or
    `REQUIRE_HUMAN` — see docs/risk-framework.md. This is enforced in code, not left to
    the LLM's judgment: the risk verdict is checked before any LLM call, and a blocking
    verdict short-circuits straight to a FORWARD=False outcome.
    """

    agent_id = "executive.chief_investment_agent.v1"
    agent_name = "Chief Investment Agent"
    agent_type = AgentType.CHIEF_INVESTMENT_AGENT
    version = "0.1.0"

    _NON_OVERRIDABLE_VERDICTS = {
        RiskVerdict.BLOCK,
        RiskVerdict.BLOCK_NEW_RISK,
        RiskVerdict.HALT,
        RiskVerdict.REJECT,
    }

    async def _execute(
        self,
        *,
        committee_decision: InvestmentCommitteeDecision,
        risk_verdict: RiskVerdict,
    ) -> AgentOutcome:
        if risk_verdict in self._NON_OVERRIDABLE_VERDICTS:
            return AgentOutcome(
                outputs={"forward_for_human_review": False, "risk_verdict": risk_verdict.value},
                reasoning_summary=(
                    f"Risk Governor verdict is {risk_verdict.value}; this trade cannot proceed to "
                    "human review regardless of committee recommendation. The Chief Investment "
                    "Agent has no authority to override this."
                ),
                confidence=1.0,
                tools=["chief_investment_agent.enforce_risk_gate"],
            )

        committee_blocks = committee_decision.recommended_action == RecommendedAction.REJECT
        forward = not committee_blocks

        detail = (
            f"AI Investment Committee recommends {committee_decision.recommended_action.value} "
            f"(consensus score {committee_decision.consensus_score}); Risk Governor verdict is "
            f"{risk_verdict.value}."
        )
        if forward:
            detail += " Forwarding to human review queue."
        else:
            detail += " Committee recommendation blocks forwarding."

        return AgentOutcome(
            outputs={
                "forward_for_human_review": forward,
                "risk_verdict": risk_verdict.value,
                "committee_recommendation": committee_decision.recommended_action.value,
            },
            reasoning_summary=detail,
            confidence=committee_decision.consensus_score,
            tools=["chief_investment_agent.route_for_review"],
        )
