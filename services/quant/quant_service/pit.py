"""Point-in-time (PIT) correctness: the single most important rule in the
Quantitative Platform (docs/architecture.md QUANTITATIVE PLATFORM: "Use publication
timestamp — not merely observation timestamp — to determine what information was
available historically. This requirement is critical.").

The bug this module exists to prevent: an `observation_time` describes what the world
looked like on some date, but `publication_time` describes when that fact actually
became knowable. EIA's weekly storage report is the canonical example — the
`observation_time` is the Friday the storage week ended, but `publication_time` is the
following Thursday, ~5 days later. A model backtested against `observation_time` alone
would "know" Friday's storage level on Friday, when in reality nobody did until the
following Thursday. That's look-ahead bias, and it silently inflates every backtest
metric that doesn't guard against it.

Every function here takes an explicit `as_of` — the moment the backtest fold or live
forecast is being evaluated "as of" — and filters strictly on `publication_time`.
Nothing in `services/quant` is allowed to read `observation_time` for filtering
purposes; `as_of_filter` is the only sanctioned way to select "what was knowable."
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, TypeVar


class HasPublicationTime(Protocol):
    publication_time: datetime


T = TypeVar("T", bound=HasPublicationTime)


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def as_of_filter(observations: list[T], as_of: datetime) -> list[T]:
    """Returns only observations that were actually knowable at `as_of` — i.e.
    `publication_time <= as_of`. This is the ONLY correct way to slice historical data
    for a forecast, a model fit, or a backtest fold in this platform.
    """
    as_of = _as_aware(as_of)
    return [o for o in observations if _as_aware(o.publication_time) <= as_of]


def latest_known_value(observations: list[T], as_of: datetime, *, value_attr: str = "value") -> T | None:
    """Among what was knowable at `as_of`, the most recently *observed* (not
    published) record — i.e. the freshest information available at that moment. Used
    by models that need "the last known price/balance as of today" without leaking
    anything published after `as_of`.
    """
    known = as_of_filter(observations, as_of)
    if not known:
        return None
    return max(known, key=lambda o: getattr(o, "observation_time"))


def assert_no_leakage(observations: list[T], as_of: datetime) -> None:
    """Defensive check a caller can run before fitting/predicting: raises if any
    observation passed in has a `publication_time` after `as_of`. Use this at model
    fit/predict boundaries as a last line of defense against a caller forgetting to
    call `as_of_filter` first.
    """
    as_of_aware = _as_aware(as_of)
    leaked = [o for o in observations if _as_aware(o.publication_time) > as_of_aware]
    if leaked:
        raise ValueError(
            f"{len(leaked)} observation(s) with publication_time after as_of={as_of_aware.isoformat()} "
            "were passed to a model boundary — this is look-ahead bias. Call as_of_filter() first."
        )
