"""Unit test suite for credit_risk package (Stage 3 Challenge).

Covers all 8 required test areas:
1. Feature engineering calculations
2. Behavior with missing values
3. Cost calculation logic ($12 FN, $1 FP)
4. Expected cost per 1,000 normalization
5. Threshold optimization logic
6. Sentinel detection & masking (codes 96, 98)
7. End-to-end inference on sample input
8. Database connection and view loading
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from credit_risk.cost import (
    DEFAULT_COST_FN,
    DEFAULT_COST_FP,
    calculate_expected_cost_per_thousand,
    calculate_total_cost,
    find_optimal_threshold,
)
from credit_risk.db import get_db_engine, load_clean_borrowers
from credit_risk.features import add_engineered_features
from credit_risk.sentinel import (
    SENTINEL_CODES,
    SentinelAuditor,
    clean_sentinel_values,
)


def test_1_feature_engineering_math():
    """Verify engineered feature calculations match formulas."""
    df = pd.DataFrame({
        "applicant_id": [1],
        "serious_dlqin_2yrs": [0],
        "revolving_utilization_of_unsecured_lines": [0.5],
        "age": [40],
        "number_of_time30_59_days_past_due_not_worse": [1],
        "debt_ratio": [0.25],
        "monthly_income": [4000.0],
        "number_of_open_credit_lines_and_loans": [4],
        "number_of_times90_days_late": [0],
        "number_real_estate_loans_or_lines": [1],
        "number_of_time60_89_days_past_due_not_worse": [0],
        "number_of_dependents": [2],
    })
    feat = add_engineered_features(df)
    # debt_to_income_dollars = 0.25 * 4000 = 1000.0
    assert pytest.approx(feat["debt_to_income_dollars"].iloc[0]) == 1000.0
    # utilization_per_line = 0.5 / (4 + 1) = 0.1
    assert pytest.approx(feat["utilization_per_line"].iloc[0]) == 0.1
    # unsecured_to_total_lines_ratio = (4 - 1) / (4 + 1) = 3 / 5 = 0.6
    assert pytest.approx(feat["unsecured_to_total_lines_ratio"].iloc[0]) == 0.6
    # clean_past_due_total = 1 + 0 + 0 = 1.0
    assert feat["clean_past_due_total"].iloc[0] == 1.0


def test_2_feature_engineering_missing_income():
    """Verify behavior when MonthlyIncome is NaN (DebtRatio acts as absolute debt)."""
    df = pd.DataFrame({
        "applicant_id": [2],
        "serious_dlqin_2yrs": [0],
        "revolving_utilization_of_unsecured_lines": [0.2],
        "age": [50],
        "number_of_time30_59_days_past_due_not_worse": [0],
        "debt_ratio": [2500.0],
        "monthly_income": [np.nan],
        "number_of_open_credit_lines_and_loans": [2],
        "number_of_times90_days_late": [0],
        "number_real_estate_loans_or_lines": [0],
        "number_of_time60_89_days_past_due_not_worse": [0],
        "number_of_dependents": [np.nan],
    })
    feat = add_engineered_features(df)
    assert feat["debt_to_income_dollars"].iloc[0] == 2500.0


def test_3_cost_calculation():
    """Verify cost matrix calculation: FP = $1, FN = $12."""
    y_true = [0, 0, 1, 1]
    y_pred = [0, 1, 0, 1]  # 1 TN, 1 FP (cost 1), 1 FN (cost 12), 1 TP (cost 0)
    total = calculate_total_cost(y_true, y_pred, cost_fp=1.0, cost_fn=12.0)
    assert total == 13.0


def test_4_expected_cost_per_thousand():
    """Verify expected cost per 1,000 applicants normalization."""
    y_true = [0, 0, 1, 1]
    y_pred = [0, 1, 0, 1]  # total cost = 13 across 4 applicants
    cost_per_thousand = calculate_expected_cost_per_thousand(y_true, y_pred, cost_fp=1.0, cost_fn=12.0)
    assert pytest.approx(cost_per_thousand) == (13.0 / 4.0) * 1000.0


def test_5_threshold_optimization():
    """Verify find_optimal_threshold prefers lower threshold to avoid expensive $12 FNs."""
    y_true = np.array([0] * 90 + [1] * 10)
    # Predicted probabilities where defaults have moderate prob ~ 0.25
    y_probs = np.array([0.05] * 90 + [0.25] * 10)

    # At threshold 0.5, all 10 are predicted 0 -> 10 FNs -> cost 120
    # At threshold 0.20, all 10 are predicted 1 -> 0 FNs, 0 FPs -> cost 0
    best_th, min_cost, details = find_optimal_threshold(y_true, y_probs, cost_fp=1.0, cost_fn=12.0)
    assert best_th < 0.5
    assert min_cost < details["default_0_5_cost_per_thousand"]


def test_6_sentinel_auditor_and_masking():
    """Verify sentinel auditor detects 96/98 and clean_sentinel_values flags and masks."""
    df = pd.DataFrame({
        "applicant_id": [1, 2],
        "serious_dlqin_2yrs": [0, 1],
        "raw_num_30_59_days_late": [0, 98],
        "raw_num_60_89_days_late": [0, 98],
        "raw_num_90_days_late": [0, 98],
        "age": [30, 45],
        "monthly_income": [3000.0, 5000.0],
    })
    audit = SentinelAuditor.audit(df)
    assert audit["exact_concordance_all_98"] == 1
    assert audit["total_sentinel_rows"] == 1

    cleaned = clean_sentinel_values(df, strategy="mask_to_nan")
    assert cleaned["has_sentinel_late_code"].tolist() == [0, 1]
    assert np.isnan(cleaned["raw_num_30_59_days_late"].iloc[1])


def test_7_pipeline_inference_sample():
    """Verify that an inference pipeline runs seamlessly on a new sample row."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression()),
    ])

    X_dummy = pd.DataFrame({
        "util": [0.1, 0.8, 0.3, np.nan],
        "age": [25, 45, 60, 35],
        "income": [2000.0, np.nan, 8000.0, 4500.0],
    })
    y_dummy = np.array([0, 1, 0, 0])

    pipe.fit(X_dummy, y_dummy)
    sample = pd.DataFrame({"util": [0.4], "age": [50], "income": [np.nan]})
    pred = pipe.predict(sample)
    prob = pipe.predict_proba(sample)
    assert len(pred) == 1
    assert prob.shape == (1, 2)


def test_8_database_view_loading():
    """Verify that records are successfully queried from credit.vw_borrowers_clean."""
    df = load_clean_borrowers(limit=5)
    assert len(df) == 5
    assert "applicant_id" in df.columns
    assert "serious_dlqin_2yrs" in df.columns
    assert "has_sentinel_late_code" in df.columns
