-- Database-Layer Data Preparation View
-- Stage 3: Machine Learning & Relational Integration
-- Purpose:
--   1. Flag & clean credit bureau sentinel values (codes 96, 98 in past-due columns).
--   2. Flag missing values (MonthlyIncome, NumberOfDependents).
--   3. Detect domain outliers (age < 18, debt ratio as absolute dollar amounts).
--   4. Expose clean, standardized features to Python/SQLAlchemy modeling pipelines.

CREATE OR REPLACE VIEW credit.vw_borrowers_clean AS
SELECT
    applicant_id,
    serious_dlqin_2yrs,
    revolving_utilization_of_unsecured_lines,
    age,
    
    -- Sentinel detection: codes 96 and 98 represent credit bureau data exceptions
    CASE 
        WHEN number_of_time30_59_days_past_due_not_worse IN (96, 98)
          OR number_of_time60_89_days_past_due_not_worse IN (96, 98)
          OR number_of_times90_days_late IN (96, 98)
        THEN TRUE
        ELSE FALSE
    END AS has_sentinel_late_code,

    -- Cleaned late count columns where sentinels are converted to NULL for downstream imputation
    CASE 
        WHEN number_of_time30_59_days_past_due_not_worse IN (96, 98) THEN NULL 
        ELSE number_of_time30_59_days_past_due_not_worse 
    END AS clean_num_30_59_days_late,

    CASE 
        WHEN number_of_time60_89_days_past_due_not_worse IN (96, 98) THEN NULL 
        ELSE number_of_time60_89_days_past_due_not_worse 
    END AS clean_num_60_89_days_late,

    CASE 
        WHEN number_of_times90_days_late IN (96, 98) THEN NULL 
        ELSE number_of_times90_days_late 
    END AS clean_num_90_days_late,

    -- Total non-sentinel past due events
    CASE 
        WHEN number_of_time30_59_days_past_due_not_worse IN (96, 98) THEN NULL 
        ELSE (
            number_of_time30_59_days_past_due_not_worse + 
            number_of_time60_89_days_past_due_not_worse + 
            number_of_times90_days_late
        )
    END AS clean_total_past_due_events,

    -- Missingness indicators
    CASE WHEN monthly_income IS NULL THEN TRUE ELSE FALSE END AS is_monthly_income_missing,
    CASE WHEN number_of_dependents IS NULL THEN TRUE ELSE FALSE END AS is_dependents_missing,

    -- Domain outlier indicators
    CASE WHEN age < 18 THEN TRUE ELSE FALSE END AS is_impossible_age,
    CASE WHEN monthly_income IS NULL AND debt_ratio > 1.0 THEN TRUE ELSE FALSE END AS is_debt_ratio_as_dollar_amount,

    -- Raw attributes preserved for full transparency
    debt_ratio,
    monthly_income,
    number_of_open_credit_lines_and_loans,
    number_real_estate_loans_or_lines,
    number_of_dependents,
    number_of_time30_59_days_past_due_not_worse AS raw_num_30_59_days_late,
    number_of_time60_89_days_past_due_not_worse AS raw_num_60_89_days_late,
    number_of_times90_days_late AS raw_num_90_days_late,
    ingested_at_utc
FROM credit.borrowers;
