"""Random Forest, XGBoost, and LightGBM forecasting models.

All three follow the same recipe: turn the univariate price series into a standard
lag-feature supervised-learning problem (features = the last `k` values, target = the
next value), fit a real tabular regressor on it, and forecast `steps_ahead` periods out
by iteratively feeding each new prediction back in as the newest lag — the standard way
to apply tabular ML regressors to time-series recursive forecasting. `_LagFeatureTreeModel`
holds that shared machinery; each subclass only supplies which regressor to fit.
"""

from __future__ import annotations

import numpy as np
from lightgbm import LGBMRegressor
from schemas import ModelType
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

from .base import ForecastModel


class _LagFeatureTreeModel(ForecastModel):
    _MIN_LAGS = 2
    _MAX_LAGS = 10

    def _build_regressor(self):
        raise NotImplementedError

    def __init__(self) -> None:
        self._regressor = None
        self._num_lags: int = 0
        self._last_window: list[float] = []
        self._residual_std: float = 0.0

    def fit(self, x: list[float], y: list[float]) -> None:
        n = len(y)
        if n < self._MIN_LAGS + 3:
            raise ValueError(f"{type(self).__name__} needs at least {self._MIN_LAGS + 3} points to fit")
        self._num_lags = max(self._MIN_LAGS, min(self._MAX_LAGS, n // 4))
        y_arr = np.asarray(y, dtype=float)

        features, targets = [], []
        for i in range(self._num_lags, n):
            features.append(y_arr[i - self._num_lags : i])
            targets.append(y_arr[i])
        x_train = np.asarray(features)
        y_train = np.asarray(targets)

        self._regressor = self._build_regressor()
        self._regressor.fit(x_train, y_train)

        fitted = self._regressor.predict(x_train)
        residuals = y_train - fitted
        self._residual_std = float(np.std(residuals)) if len(residuals) >= 2 else 0.0
        self._last_window = list(y_arr[-self._num_lags :])

    def predict(self, steps_ahead: int) -> float:
        if self._regressor is None:
            raise RuntimeError("Model must be fit() before predict()")
        window = list(self._last_window)
        next_value = window[-1]
        for _ in range(steps_ahead):
            features = np.asarray(window[-self._num_lags :]).reshape(1, -1)
            next_value = float(self._regressor.predict(features)[0])
            window.append(next_value)
        return next_value

    def predict_with_uncertainty(self, steps_ahead: int) -> tuple[float, float]:
        # Random-walk-style horizon scaling on the in-sample residual std, same
        # convention NaivePersistenceModel/LinearRegressionModel use.
        return self.predict(steps_ahead), self._residual_std * (steps_ahead**0.5)


class RandomForestModel(_LagFeatureTreeModel):
    model_type = ModelType.RANDOM_FOREST
    version = "1.0.0"

    def _build_regressor(self):
        # n_jobs=1 (not -1): walk-forward backtesting calls fit() once per fold
        # (dozens of times), and on the small lag-feature tables this model trains on
        # (tens of rows), multiprocess pool startup overhead swamps any parallel
        # speedup — n_jobs=-1 measured ~19s for a 37-fold backtest here vs. ~1s at
        # n_jobs=1. n_estimators is sized to this same small-data regime, not tuned
        # for a production-scale dataset.
        return RandomForestRegressor(n_estimators=30, max_depth=6, random_state=42, n_jobs=1)


class XGBoostModel(_LagFeatureTreeModel):
    model_type = ModelType.XGBOOST
    version = "1.0.0"

    def _build_regressor(self):
        return XGBRegressor(
            n_estimators=50, max_depth=4, learning_rate=0.05, random_state=42, n_jobs=1, verbosity=0
        )


class LightGBMModel(_LagFeatureTreeModel):
    model_type = ModelType.LIGHTGBM
    version = "1.0.0"

    def _build_regressor(self):
        # See RandomForestModel's n_jobs note — same reasoning applies here, and
        # LightGBM's own per-call thread-pool spin-up is what made it the single
        # slowest model of the eight in walk-forward backtesting before this fix.
        return LGBMRegressor(
            n_estimators=50,
            max_depth=4,
            learning_rate=0.05,
            random_state=42,
            n_jobs=1,
            verbosity=-1,
            min_child_samples=1,
            min_data_in_bin=1,
        )
