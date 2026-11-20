"""Feature engineering and pre-decision leakage audit for Stage 3 Challenge.

All features are derived exclusively from data available strictly BEFORE
the loan origination decision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add four features from debt, income and credit history at application time.

    Accept both the original CSV headers and the database column names.
    """
    out = df.copy()

    # 1. Debt in dollars
    income = out["monthly_income"] if "monthly_income" in out.columns else out.get("MonthlyIncome")
    debt_ratio = out["debt_ratio"] if "debt_ratio" in out.columns else out.get("DebtRatio")
    if income is not None and debt_ratio is not None:
        out["debt_to_income_dollars"] = np.where(
            income.notna(),
            debt_ratio * income,
            debt_ratio,  # When income was omitted in this dataset, debt_ratio stores dollar payment
        )

    # 2. Utilization per open credit line
    util = (
        out["revolving_utilization_of_unsecured_lines"]
        if "revolving_utilization_of_unsecured_lines" in out.columns
        else out.get("RevolvingUtilizationOfUnsecuredLines", 0.0)
    )
    open_lines = (
        out["number_of_open_credit_lines_and_loans"]
        if "number_of_open_credit_lines_and_loans" in out.columns
        else out.get("NumberOfOpenCreditLinesAndLoans", 0.0)
    )
    out["utilization_per_line"] = util / (open_lines + 1.0)

    # 3. Unsecured lines ratio
    real_estate = (
        out["number_real_estate_loans_or_lines"]
        if "number_real_estate_loans_or_lines" in out.columns
        else out.get("NumberRealEstateLoansOrLines", 0.0)
    )
    unsecured_lines = np.maximum(open_lines - real_estate, 0.0)
    out["unsecured_to_total_lines_ratio"] = unsecured_lines / (open_lines + 1.0)

    # 4. Clean past due total
    if "clean_total_past_due_events" in out.columns:
        out["clean_past_due_total"] = out["clean_total_past_due_events"].fillna(0.0)
    else:
        # Compute from raw if clean columns are absent
        late_payment_columns = (
            ("number_of_time30_59_days_past_due_not_worse", "NumberOfTime30-59DaysPastDueNotWorse"),
            ("number_of_time60_89_days_past_due_not_worse", "NumberOfTime60-89DaysPastDueNotWorse"),
            ("number_of_times90_days_late", "NumberOfTimes90DaysLate"),
        )
        total = 0
        for database_name, csv_name in late_payment_columns:
            counts = out.get(database_name, out.get(csv_name, 0))
            # Codes 96 and 98 indicate missing payment history.
            total = total + np.where(np.isin(counts, (96, 98)), 0, counts)
        out["clean_past_due_total"] = total

    return out
