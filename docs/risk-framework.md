# Risk Framework

## 1. Principle

> **The Risk Governor has absolute veto authority. No LLM may override a failed hard risk rule.**

Risk management is organizationally and technically **independent** from the trading/research
agents. It runs as its own service (`services/risk`), is called out-of-band by the workflow that
moves a `TradeIdea` toward `APPROVED_FOR_PAPER_TRADING`, and its verdict is enforced at the data
layer: the `approvals` state machine cannot transition into `APPROVED_FOR_PAPER_TRADING` without
a matching `risk_checks` row whose verdict is `ALLOW` (or `REQUIRE_HUMAN` subsequently cleared by
an authorized human).

## 2. Independent Risk Organization

- **Market Risk Agent** — price/vol exposure, VaR/ES contribution of the proposed trade
- **Portfolio Risk Agent** — portfolio-level Greeks, correlation, concentration effects
- **Liquidity Risk Agent** — instrument liquidity, expected slippage on exit
- **Data Risk Agent** — checks the data underlying the trade for staleness/gaps/conflicts
- **Model Risk Agent** — checks the model/strategy version is an approved, validated version
- **Risk Governor** — deterministic rules engine; final arbiter

Risk agents may use LLM reasoning to *explain* risk (narrative risk summaries), but every
**blocking decision** is produced by deterministic code in the Risk Governor, not by an LLM.

## 3. Risk Calculations (`services/risk/app/metrics.py`)

Gross exposure, net exposure, delta, gamma, vega, realized P&L, unrealized P&L, daily P&L,
Value-at-Risk (historical simulation, parametric fallback), Expected Shortfall, maximum
drawdown, correlation matrix, concentration (Herfindahl by instrument/sector), liquidity score.

## 4. Configurable Limits (`risk_limits` table)

`max_position_size`, `max_risk_per_trade`, `max_daily_loss`, `max_drawdown`,
`max_portfolio_var`, `max_sector_exposure`, `max_contract_exposure`,
`max_correlated_exposure` — versioned, effective-dated, settable only by `RISK_MANAGER`/`ADMIN`
roles, changes written to `audit_log`.

## 5. Risk Governor — Deterministic Rules

Implemented as an ordered, pure-function rule chain
(`services/risk/app/governor.py::RiskGovernor.evaluate`). Each rule takes typed inputs (no LLM
calls) and returns a verdict; the first `BLOCK`/`HALT`/`REJECT` short-circuits the chain.

```
IF required market data is stale                        -> BLOCK
IF a critical provider is unavailable                    -> BLOCK or REQUIRE_HUMAN (configurable)
IF proposed position exceeds a configured limit           -> BLOCK
IF daily loss limit exceeded                              -> BLOCK_NEW_RISK
IF drawdown limit exceeded                                -> HALT
IF strategy is not on the approved-strategy list           -> BLOCK
IF model version is not on the approved-model registry     -> BLOCK
IF trade confidence is below the configured threshold      -> REJECT
IF abnormal volatility threshold is exceeded                -> REQUIRE_HUMAN_APPROVAL
IF the Risk Governor service itself is unavailable          -> FAIL CLOSED (treated as BLOCK)
```

Verdicts: `ALLOW`, `BLOCK`, `BLOCK_NEW_RISK`, `HALT`, `REJECT`, `REQUIRE_HUMAN`. `HALT` also
flips a global `trading_halted` flag that blocks *all* new trade ideas from proceeding, not just
the triggering one, until an `ADMIN`/`RISK_MANAGER` clears it explicitly.

This rule chain has no dependency on network calls beyond reading already-fetched limits/state
from Postgres/Redis, is fully deterministic given its inputs, and is covered by the highest test
coverage bar in the codebase (see `docs/architecture.md` §"Testing" and
`tests/risk/test_governor.py`).

## 6. Human Approval Workflow

States: `DRAFT → AI_REVIEW → RISK_REVIEW → HUMAN_REVIEW → APPROVED_FOR_PAPER_TRADING`, with
`REJECTED` / `EXPIRED` as terminal-before-execution states, and
`EXECUTED_SIMULATION → CLOSED` after paper execution. Only `TRADER`/`RISK_MANAGER`/`ADMIN` roles
can act; every action (`approve`, `reject`, `modify`, `challenge`, `request_more_analysis`,
`reduce_position`, `change_invalidation_condition`) is appended to `approvals.actions` — never
overwritten.

## 7. Stress Testing

`services/risk/app/scenarios.py` implements a scenario engine with the initial scenario set
(polar vortex, ±15% weather, major hurricane, Freeport-style LNG terminal outage, 2/5 Bcf/d
production outage, record production, LNG feedgas decline, pipeline disruption, EIA storage
surprise ±20 Bcf, TTF collapse/spike). Each scenario reports portfolio P&L, strategy P&L, margin
impact, VaR impact, and largest risk contributor. Scenarios are deterministic shocks applied to
current positions/curves — no live capital is at risk since only paper positions exist.

## 8. No Live Trading

`services/paper-execution` is the only `ExecutionAdapter` implementation shipped. The interface
is designed so a future regulated broker/exchange adapter can be added later, but doing so
requires: independent model validation, legal/compliance review, credentials & entitlements,
explicit human authorization, and configured risk limits — none of which exist in this
repository by default, and none of which any agent can grant itself.
