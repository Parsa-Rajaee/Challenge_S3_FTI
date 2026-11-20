"""Production training and inference pipeline for Stage 3 Credit Risk ML.

Provides model training, serialization, and high-performance inference
with cost-sensitive optimal decision thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from .cost import (
    DEFAULT_COST_FN,
    DEFAULT_COST_FP,
    calculate_expected_cost_per_thousand,
    find_optimal_threshold,
)
from .db import load_clean_borrowers
from .features import add_engineered_features
from .sentinel import clean_sentinel_values

FEATURE_COLUMNS: list[str] = [
    "revolving_utilization_of_unsecured_lines",
    "age",
    "debt_ratio",
    "monthly_income",
    "number_of_open_credit_lines_and_loans",
    "number_real_estate_loans_or_lines",
    "number_of_dependents",
    "has_sentinel_late_code",
    "clean_num_30_59_days_late",
    "clean_num_60_89_days_late",
    "clean_num_90_days_late",
    "clean_total_past_due_events",
    "debt_to_income_dollars",
    "utilization_per_line",
    "unsecured_to_total_lines_ratio",
    "clean_past_due_total",
]

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts"
DEFAULT_MODEL_PATH = DEFAULT_ARTIFACT_DIR / "credit_risk_model.joblib"


def get_default_model_path() -> Path:
    """Resolve default model artifact path across different working directories."""
    candidates = [
        DEFAULT_MODEL_PATH,
        Path("artifacts/credit_risk_model.joblib"),
        Path("part3/stage-3-machine-learning/artifacts/credit_risk_model.joblib"),
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return DEFAULT_MODEL_PATH


@dataclass
class CreditRiskPipeline:
    """Production wrapper bundling model, feature transformation, threshold, and costs."""

    classifier: HistGradientBoostingClassifier = field(
        default_factory=lambda: HistGradientBoostingClassifier(
            random_state=42, max_iter=120, max_leaf_nodes=31
        )
    )
    optimal_threshold: float = 0.0691
    cost_fn: float = DEFAULT_COST_FN
    cost_fp: float = DEFAULT_COST_FP
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    metadata: dict[str, Any] = field(default_factory=dict)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply leak-free sentinel cleaning and feature engineering to raw input."""
        cleaned = clean_sentinel_values(df)
        feat = add_engineered_features(cleaned)

        missing_cols = [c for c in self.feature_names if c not in feat.columns]
        if missing_cols:
            raise ValueError(f"Input DataFrame is missing required feature columns: {missing_cols}")

        return feat[self.feature_names].copy()

    def fit(
        self,
        X_df: pd.DataFrame,
        y: pd.Series | np.ndarray,
        *,
        optimize_threshold: bool = True,
    ) -> CreditRiskPipeline:
        """Fit model and calculate cost-optimal decision threshold."""
        X_ready = self.prepare_features(X_df)
        y_arr = np.asarray(y)

        self.classifier.fit(X_ready, y_arr)

        if optimize_threshold:
            train_probs = self.classifier.predict_proba(X_ready)[:, 1]
            best_th, min_cost, details = find_optimal_threshold(
                y_arr, train_probs, cost_fp=self.cost_fp, cost_fn=self.cost_fn
            )
            self.optimal_threshold = float(best_th)
            self.metadata["train_min_cost_per_thousand"] = float(min_cost)

        self.metadata["n_train_samples"] = len(y_arr)
        self.metadata["positive_rate"] = float(np.mean(y_arr))
        self.metadata["trained_at_utc"] = datetime.now(timezone.utc).isoformat()
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Estimate default probability P(SeriousDlqin2yrs=1)."""
        X_ready = self.prepare_features(df)
        return self.classifier.predict_proba(X_ready)[:, 1]

    def predict(self, df: pd.DataFrame, threshold: float | None = None) -> np.ndarray:
        """Binary classification using cost-optimal threshold (default: 0.0691)."""
        th = threshold if threshold is not None else self.optimal_threshold
        probs = self.predict_proba(df)
        return (probs >= th).astype(int)

    def predict_decisions(
        self, df: pd.DataFrame, threshold: float | None = None
    ) -> pd.DataFrame:
        """Generate structured business decisions for credit applicants."""
        th = threshold if threshold is not None else self.optimal_threshold
        probs = self.predict_proba(df)
        preds = (probs >= th).astype(int)

        out = pd.DataFrame(index=df.index)
        if "applicant_id" in df.columns:
            out["applicant_id"] = df["applicant_id"]

        out["default_probability"] = np.round(probs, 4)
        out["predicted_default"] = preds
        out["decision"] = np.where(preds == 1, "DECLINE", "APPROVE")

        # Categorize risk tiers
        conditions = [
            probs >= 0.20,
            probs >= th,
            probs < th,
        ]
        choices = ["CRITICAL_RISK", "MODERATE_RISK", "LOW_RISK"]
        out["risk_tier"] = np.select(conditions, choices, default="LOW_RISK")

        # Record decision threshold used
        out["decision_threshold"] = round(th, 4)
        return out

    def save(self, filepath: str | Path | None = None) -> Path:
        """Serialize pipeline and metadata to a joblib file."""
        target = Path(filepath) if filepath else DEFAULT_MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target)
        return target

    @classmethod
    def load(cls, filepath: str | Path | None = None) -> CreditRiskPipeline:
        """Deserialize a trained pipeline from a joblib file."""
        target = Path(filepath) if filepath else get_default_model_path()
        if not target.is_file():
            raise FileNotFoundError(
                f"Model artifact not found at {target}. Please run train_and_save_production_model() first."
            )
        pipeline = joblib.load(target)
        if not isinstance(pipeline, cls):
            raise TypeError(f"Loaded object is of type {type(pipeline)}, expected {cls}.")
        return pipeline


def train_and_save_production_model(
    output_path: str | Path | None = None,
    test_size: float = 0.20,
    random_seed: int = 42,
) -> tuple[CreditRiskPipeline, dict[str, float]]:
    """Fit the model, select a threshold on calibration rows, and score the held-out test set."""
    df = load_clean_borrowers()
    target_col = "serious_dlqin_2yrs"
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' missing from data.")

    y = df[target_col]
    X_train, X_test, y_train, y_test = train_test_split(
        df, y, test_size=test_size, random_state=random_seed, stratify=y
    )

    # Reserve calibration rows from training; only the final evaluation uses X_test.
    X_fit, X_calibration, y_fit, y_calibration = train_test_split(
        X_train, y_train, test_size=0.20, random_state=random_seed, stratify=y_train
    )
    pipeline = CreditRiskPipeline()
    pipeline.fit(X_fit, y_fit, optimize_threshold=False)
    costs = {"cost_fp": pipeline.cost_fp, "cost_fn": pipeline.cost_fn}
    calibration_probs = pipeline.predict_proba(X_calibration)
    best_th, calibration_cost, _ = find_optimal_threshold(y_calibration, calibration_probs, **costs)

    test_probs = pipeline.predict_proba(X_test)
    test_auc = float(roc_auc_score(y_test, test_probs))
    test_cost = calculate_expected_cost_per_thousand(y_test, test_probs >= best_th, **costs)
    default_cost = calculate_expected_cost_per_thousand(y_test, test_probs >= 0.5, **costs)
    baseline_cost = calculate_expected_cost_per_thousand(y_test, np.zeros_like(y_test), **costs)
    cost_reduction = (1.0 - test_cost / baseline_cost) * 100.0

    pipeline.optimal_threshold = float(best_th)
    pipeline.metadata.update({
        "test_auc": test_auc,
        "calibration_min_cost_per_thousand": float(calibration_cost),
        "test_cost_per_thousand": float(test_cost),
        "baseline_cost_per_thousand": float(baseline_cost),
        "cost_reduction_pct": float(cost_reduction),
        "default_0_5_cost_per_thousand": float(default_cost),
    })

    pipeline.save(output_path)

    metrics = {
        "auc": test_auc,
        "optimal_threshold": float(best_th),
        "optimal_cost_per_thousand": float(test_cost),
        "baseline_cost_per_thousand": float(baseline_cost),
        "cost_reduction_pct": float(cost_reduction),
    }
    return pipeline, metrics
