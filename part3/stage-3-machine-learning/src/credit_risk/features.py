"""Feature engineering and pre-decision leakage audit for Stage 3 Challenge.

All features are derived exclusively from data available strictly BEFORE
the loan origination decision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 4 domain-justified features with zero lookahead leakage.

    Feature 1: debt_to_income_dollars
      - Hypothesis: Absolute monthly debt obligations in dollars measure cash-flow
        fragility more accurately than ratios alone.
      - Availability: Verified at loan application via payslips and credit bureau debts.

    Feature 2: utilization_per_line
      - Hypothesis: High revolving utilization concentrated across few open accounts
        signals credit card balance distress rather than dispersed operational credit.
      - Availability: Reported by credit bureau at application time.

    Feature 3: unsecured_to_total_lines_ratio
      - Hypothesis: Higher proportion of unsecured credit lines compared to secured real
        estate mortgages reflects higher credit risk.
      - Availability: Reported in credit bureau tradeline summary.

    Feature 4: clean_past_due_total
      - Hypothesis: Total non-sentinel past-due delinquency events across 30-59, 60-89,
        and 90+ buckets capture cumulative delinquency history.
      - Availability: Historical bureau delinquency record prior to application.
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
        c1 = out.get("number_of_time30_59_days_past_due_not_worse", out.get("NumberOfTime30-59DaysPastDueNotWorse", 0))
        c2 = out.get("number_of_time60_89_days_past_due_not_worse", out.get("NumberOfTime60-89DaysPastDueNotWorse", 0))
        c3 = out.get("number_of_times90_days_late", out.get("NumberOfTimes90DaysLate", 0))
        # Mask sentinels
        m1 = np.where(np.isin(c1, (96, 98)), 0, c1)
        m2 = np.where(np.isin(c2, (96, 98)), 0, c2)
        m3 = np.where(np.isin(c3, (96, 98)), 0, c3)
        out["clean_past_due_total"] = m1 + m2 + m3

    return out
