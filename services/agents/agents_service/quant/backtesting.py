from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from quant_service import InsufficientDataError, walk_forward_evaluate
from quant_service.models import implemented_model_types
from schemas import AgentStatus, AgentType, ForecastHorizon, TimeSeriesObservation


class BacktestingAgent(BaseAgent):
    """Quantitative Team: walk-forward validation of every implemented model
    (docs/architecture.md "prevent look-ahead bias... this requirement is critical").
    Runs every implemented `ModelType` against the same price history and horizon so
    they can be compared on equal footing — "do NOT assume a deep learning model is
    superior" applies equally to assuming any model is superior without evidence.

    `step_days=15` (rather than `walk_forward_evaluate`'s own finer-grained default)
    is this agent's own choice: it runs automatically on every research cycle, across
    all 8 implemented models, so it trades some fold count (and thus some backtest
    confidence — already honestly reflected in `confidence = min(0.8, n_folds / 50)`
    below) for keeping every automatic cycle fast. A deeper, slower analysis is still
    available by calling `walk_forward_evaluate` directly with a smaller `step_days`.
    """

    agent_id = "quant.backtesting.v1"
    agent_name = "Backtesting Agent"
    agent_type = AgentType.BACKTESTING
    version = "0.1.0"

    async def _execute(
        self,
        *,
        instrument: str,
        price_history: list[TimeSeriesObservation],
        horizon: ForecastHorizon = ForecastHorizon.SEVEN_DAY,
        train_window_days: int = 60,
        step_days: int = 15,
    ) -> AgentOutcome:
        results = {}
        errors = []
        for model_type in implemented_model_types():
            try:
                result = walk_forward_evaluate(
                    model_type=model_type,
                    observations=price_history,
                    instrument=instrument,
                    horizon=horizon,
                    train_window_days=train_window_days,
                    step_days=step_days,
                )
                results[model_type.value] = result.model_dump(mode="json")
            except InsufficientDataError as exc:
                errors.append(str(exc))

        if not results:
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary="Insufficient price history for any walk-forward backtest fold.",
                errors=[],
            )

        best_model = max(results.items(), key=lambda kv: kv[1]["directional_accuracy"])

        prompt = (
            f"Backtested {len(results)} model(s) on {instrument} over {horizon.value}; "
            f"{best_model[0]} had the best directional accuracy ({best_model[1]['directional_accuracy']:.0%}). "
            "One sentence for a trading desk, noting sample size limits confidence."
        )
        llm_response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )
        reasoning = (
            f"{best_model[0]} leads on directional accuracy ({best_model[1]['directional_accuracy']:.0%}) "
            f"across {best_model[1]['n_folds']} walk-forward folds. {llm_response.content}"
        )

        return AgentOutcome(
            outputs={"results_by_model": results, "best_model": best_model[0]},
            reasoning_summary=reasoning,
            confidence=min(0.8, best_model[1]["n_folds"] / 50),
            tools=["quant_service.backtesting"],
        )
