"""Sentinel values detection, auditing, and handling for Stage 3 Challenge.

In Give Me Some Credit, the delinquency count columns contain credit bureau
sentinel / error codes (96 and 98). Treating them as numerical counts distorts
linear and tree-based models.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

SENTINEL_CODES: tuple[int, ...] = (96, 98)

LATE_COLUMNS: tuple[str, ...] = (
    "number_of_time30_59_days_past_due_not_worse",
    "number_of_time60_89_days_past_due_not_worse",
    "number_of_times90_days_late",
)

RAW_LATE_COLUMNS: tuple[str, ...] = (
    "NumberOfTime30-59DaysPastDueNotWorse",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfTimes90DaysLate",
)


VIEW_RAW_COLUMNS = (
    "raw_num_30_59_days_late",
    "raw_num_60_89_days_late",
    "raw_num_90_days_late",
)


def _late_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map each payment period to its original count, even on prepared frames."""
    columns = {}
    for canonical, csv_name, view_name in zip(LATE_COLUMNS, RAW_LATE_COLUMNS, VIEW_RAW_COLUMNS):
        for name in (view_name, canonical, csv_name):
            if name in df:
                columns[canonical] = name
                break
    return columns


class SentinelAuditor:
    """Audit credit bureau codes 96 and 98 and count domain anomalies."""

    @staticmethod
    def audit(df: pd.DataFrame) -> dict[str, Any]:
        resolved = list(_late_columns(df).values())
        counts = df[resolved]
        sentinel_mask = counts.isin(SENTINEL_CODES).any(axis=1)
        counts_96 = (counts == 96).sum().astype(int).to_dict()
        counts_98 = (counts == 98).sum().astype(int).to_dict()
        all_96 = int((counts == 96).all(axis=1).sum()) if len(resolved) == 3 else 0
        all_98 = int((counts == 98).all(axis=1).sum()) if len(resolved) == 3 else 0
        any_sentinel = int(sentinel_mask.sum())

        target_col = "serious_dlqin_2yrs" if "serious_dlqin_2yrs" in df else "SeriousDlqin2yrs"
        sentinel_default_rate = None
        normal_default_rate = None
        if target_col in df and len(resolved) == 3:
            if sentinel_mask.any():
                sentinel_default_rate = float(df.loc[sentinel_mask, target_col].mean())
            if (~sentinel_mask).any():
                normal_default_rate = float(df.loc[~sentinel_mask, target_col].mean())

        # Domain anomalies
        age_col = "age" if "age" in df.columns else None
        zero_age_count = int((df[age_col] == 0).sum()) if age_col else 0

        income_col = "monthly_income" if "monthly_income" in df.columns else ("MonthlyIncome" if "MonthlyIncome" in df.columns else None)
        missing_income = int(df[income_col].isna().sum()) if income_col else 0

        return {
            "columns_audited": resolved,
            "counts_96": counts_96,
            "counts_98": counts_98,
            "exact_concordance_all_98": all_98,
            "exact_concordance_all_96": all_96,
            "total_sentinel_rows": any_sentinel,
            "sentinel_default_rate": sentinel_default_rate,
            "normal_default_rate": normal_default_rate,
            "impossible_age_zero_count": zero_age_count,
            "missing_income_count": missing_income,
        }


def clean_sentinel_values(
    df: pd.DataFrame,
    *,
    strategy: str = "mask_to_nan",
    replacement_value: float = np.nan,
) -> pd.DataFrame:
    """Return a DataFrame copy with sentinel values handled according to strategy."""
    out = df.copy()
    columns = _late_columns(out)
    resolved = list(columns.values())

    if not resolved:
        return out

    # Add boolean sentinel indicator
    sentinel_mask = pd.Series(False, index=out.index)
    for c in resolved:
        sentinel_mask = sentinel_mask | out[c].isin(SENTINEL_CODES)

    out["has_sentinel_late_code"] = sentinel_mask.astype(int)

    if strategy == "mask_to_nan":
        for c in resolved:
            out[c] = out[c].replace(list(SENTINEL_CODES), replacement_value)
    elif strategy == "replace_with_zero":
        for c in resolved:
            out[c] = out[c].replace(list(SENTINEL_CODES), 0)

    # Populate standardized clean past-due columns if not already present
    for canonical, alias in zip(LATE_COLUMNS, VIEW_RAW_COLUMNS):
        cleaned_name = alias.replace("raw_", "clean_", 1)
        if cleaned_name not in out and canonical in columns:
            out[cleaned_name] = out[columns[canonical]].replace(list(SENTINEL_CODES), np.nan)

    clean_counts = [alias.replace("raw_", "clean_", 1) for alias in VIEW_RAW_COLUMNS]
    if "clean_total_past_due_events" not in out and all(name in out for name in clean_counts):
        total = out[clean_counts].sum(axis=1)
        out["clean_total_past_due_events"] = total.mask(sentinel_mask)

    return out


class SentinelTransformer(BaseEstimator, TransformerMixin):
    """Scikit-Learn Transformer for handling sentinel values inside pipelines.

    Prevents data leakage by fitting no dataset statistics or computing
    deterministic transformations purely from domain definitions.
    """

    def __init__(self, late_cols: list[str] | None = None, strategy: str = "mask_to_nan"):
        self.late_cols = late_cols
        self.strategy = strategy

    def fit(self, X: pd.DataFrame, y: Any = None) -> SentinelTransformer:
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        cols = self.late_cols or [c for c in LATE_COLUMNS if c in X.columns]
        X_out = X.copy()
        sentinel_mask = pd.Series(False, index=X_out.index)
        for c in cols:
            if c in X_out.columns:
                sentinel_mask = sentinel_mask | X_out[c].isin(SENTINEL_CODES)

        X_out["has_sentinel_late_code"] = sentinel_mask.astype(float)
        for c in cols:
            if c in X_out.columns:
                if self.strategy == "mask_to_nan":
                    X_out[c] = X_out[c].replace(list(SENTINEL_CODES), np.nan)
                elif self.strategy == "replace_with_zero":
                    X_out[c] = X_out[c].replace(list(SENTINEL_CODES), 0.0)
        return X_out
