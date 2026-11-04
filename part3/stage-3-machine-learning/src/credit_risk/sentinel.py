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


def _resolve_col(df: pd.DataFrame, col: str) -> str:
    if col in df.columns:
        return col
    # Check lowercase / snake_case mapping
    mapping = {
        "NumberOfTime30-59DaysPastDueNotWorse": "number_of_time30_59_days_past_due_not_worse",
        "NumberOfTime60-89DaysPastDueNotWorse": "number_of_time60_89_days_past_due_not_worse",
        "NumberOfTimes90DaysLate": "number_of_times90_days_late",
        "raw_num_30_59_days_late": "number_of_time30_59_days_past_due_not_worse",
        "raw_num_60_89_days_late": "number_of_time60_89_days_past_due_not_worse",
        "raw_num_90_days_late": "number_of_times90_days_late",
    }
    for k, v in mapping.items():
        if col in (k, v):
            if k in df.columns:
                return k
            if v in df.columns:
                return v
    return col


class SentinelAuditor:
    """Audits credit bureau sentinel values (96, 98) and domain anomalies."""

    @staticmethod
    def audit(df: pd.DataFrame) -> dict[str, Any]:
        """Perform full inspection of sentinel values across delinquency columns."""
        resolved = [_resolve_col(df, c) for c in LATE_COLUMNS if _resolve_col(df, c) in df.columns]

        counts_96: dict[str, int] = {}
        counts_98: dict[str, int] = {}
        for c in resolved:
            counts_96[c] = int((df[c] == 96).sum())
            counts_98[c] = int((df[c] == 98).sum())

        # Check co-occurrence
        if len(resolved) == 3:
            c1, c2, c3 = resolved
            all_98 = int(((df[c1] == 98) & (df[c2] == 98) & (df[c3] == 98)).sum())
            all_96 = int(((df[c1] == 96) & (df[c2] == 96) & (df[c3] == 96)).sum())
            any_sentinel = int(
                ((df[c1].isin(SENTINEL_CODES)) | (df[c2].isin(SENTINEL_CODES)) | (df[c3].isin(SENTINEL_CODES))).sum()
            )
        else:
            all_98 = 0
            all_96 = 0
            any_sentinel = sum(counts_96.values()) + sum(counts_98.values())

        # Target delinquency rate among sentinel vs non-sentinel
        target_col = "serious_dlqin_2yrs" if "serious_dlqin_2yrs" in df.columns else "SeriousDlqin2yrs"
        sentinel_default_rate = None
        normal_default_rate = None
        if target_col in df.columns and len(resolved) == 3:
            c1, c2, c3 = resolved
            sentinel_mask = (df[c1].isin(SENTINEL_CODES)) | (df[c2].isin(SENTINEL_CODES)) | (df[c3].isin(SENTINEL_CODES))
            if sentinel_mask.sum() > 0:
                sentinel_default_rate = float(df.loc[sentinel_mask, target_col].mean())
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
    resolved = [_resolve_col(out, c) for c in LATE_COLUMNS if _resolve_col(out, c) in out.columns]

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
