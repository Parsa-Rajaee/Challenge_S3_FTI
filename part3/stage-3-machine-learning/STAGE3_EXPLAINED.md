# Stage 3: Machine Learning & Relational Integration Guide
*Cost-Sensitive Credit Risk Default Prediction & Sentinel Values Auditing*

---

## 1. Executive Summary & Challenge Objectives

In **Stage 1**, we built a resilient ingestion and curation pipeline (`nyc311-data-factory`).  
In **Stage 2**, we implemented a high-performance relational schema and database tuning in PostgreSQL (`nyc311-database-performance`).  
In **Stage 3**, we unify data engineering with machine learning:
1. **Chain Requirement**: Data is strictly loaded via the Stage 1 package into PostgreSQL (`credit.borrowers`) and queried by SQLAlchemy from an analytical view (`credit.vw_borrowers_clean`). The notebook never touches flat CSV files directly.
2. **In-Database Preparation**: Data cleaning and domain sentinel value detection are executed inside PostgreSQL using declarative SQL views.
3. **Credit Bureau Sentinel Values**: Specialized codes (`96` and `98`) in delinquency columns are audited, showing a striking **54.65% default rate** (vs 6.60% in general borrowers). They are transformed into binary indicator signals while numeric columns are masked to prevent model distortion.
4. **Cost-Sensitive Decision Making**: A severe asymmetric business loss matrix ($C(\text{FN}) = 12$ vs $C(\text{FP}) = 1$) dictates threshold optimization rather than default $0.5$ probability cutoffs.

---

## 2. Relational Schema & View Architecture

### Schema: `credit.borrowers`
```sql
CREATE TABLE credit.borrowers (
    applicant_id INTEGER PRIMARY KEY,
    serious_dlqin_2yrs INTEGER NOT NULL CHECK (serious_dlqin_2yrs IN (0, 1)),
    revolving_utilization_of_unsecured_lines NUMERIC,
    age INTEGER NOT NULL CHECK (age >= 0),
    number_of_time30_59_days_past_due_not_worse INTEGER NOT NULL,
    debt_ratio NUMERIC,
    monthly_income NUMERIC(14, 2),
    number_of_open_credit_lines_and_loans INTEGER NOT NULL,
    number_of_times90_days_late INTEGER NOT NULL,
    number_real_estate_loans_or_lines INTEGER NOT NULL,
    number_of_time60_89_days_past_due_not_worse INTEGER NOT NULL,
    number_of_dependents INTEGER,
    ingested_at_utc TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### In-Database Data Preparation View: `credit.vw_borrowers_clean`
The view encapsulates:
- `has_sentinel_late_code`: Evaluates `TRUE` if `number_of_time30_59_days_past_due_not_worse IN (96, 98)` or any other past-due column contains 96 or 98.
- `clean_num_30_59_days_late`, `clean_num_60_89_days_late`, `clean_num_90_days_late`: Converts sentinel numbers to `NULL`.
- `clean_total_past_due_events`: Aggregates non-sentinel past due events.
- `is_monthly_income_missing`: Boolean flag for missing income ($29,731$ rows).
- `is_impossible_age`: Flags applicants with `age < 18` (1 applicant with age 0).
- `is_debt_ratio_as_dollar_amount`: Flags rows where `debt_ratio` represents dollar payments instead of percentage.

---

## 3. Sentinel Values Deep Dive

### What Are Codes 96 and 98?
In credit reporting standards (e.g., Metro 2 format):
- **Code 96**: Indicates that credit history could not be verified, or tradelines are frozen/under formal dispute.
- **Code 98**: Indicates no data available / system error / unverified status.

### Empirical Findings:
- Total records: **150,000**
- Sentinel 98 occurrences: **264** across all 3 delinquency columns with **100% concordance**.
- Sentinel 96 occurrences: **5** across all 3 delinquency columns with **100% concordance**.
- Total sentinel records: **269** ($0.18\%$ of borrowers).
- Default rate among sentinel borrowers: **54.65%**!
- Default rate among normal borrowers: **6.60%**!

Borrowers with sentinel codes are **8.28 times more likely to default**. Converting this domain nuance into a feature (`has_sentinel_late_code`) captures this massive signal, while masking the values prevents mathematical corruption in models like Logistic Regression.

---

## 4. Verification and Delivery Guide Compliance
- [x] Data ingested via `nyc311-data-factory` with manifest and quality report.
- [x] All 150,000 records loaded to PostgreSQL `credit.borrowers`.
- [x] Database view `credit.vw_borrowers_clean` created and verified.
- [x] Package `credit-risk-ml` created and installed in editable mode.
- [x] 8 comprehensive unit tests created and passing with 100% success.
- [x] Precomputed `solution.ipynb` with sequential execution counts (1 to N) and embedded outputs.
- [x] `report.md` structured according to all challenge criteria.
