-- Schema definition for Give Me Some Credit (Stage 3 Challenge)
-- Designed for PostgreSQL 16+

CREATE SCHEMA IF NOT EXISTS credit;

CREATE TABLE IF NOT EXISTS credit.borrowers (
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

CREATE INDEX IF NOT EXISTS idx_borrowers_target ON credit.borrowers (serious_dlqin_2yrs);
CREATE INDEX IF NOT EXISTS idx_borrowers_age ON credit.borrowers (age);
