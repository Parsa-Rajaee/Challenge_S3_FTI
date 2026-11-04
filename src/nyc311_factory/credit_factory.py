"""Credit risk file ingestion factory for Stage 3 Challenge.

Extends the Stage 1 data factory architecture to support file-based data sources
(cs-training.csv), enforcing validation, quarantine, run manifest generation,
and atomic database upsert into PostgreSQL.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .exceptions import DataValidationError


CORE_CREDIT_COLUMNS = (
    "SeriousDlqin2yrs",
    "RevolvingUtilizationOfUnsecuredLines",
    "age",
    "NumberOfTime30-59DaysPastDueNotWorse",
    "DebtRatio",
    "MonthlyIncome",
    "NumberOfOpenCreditLinesAndLoans",
    "NumberOfTimes90DaysLate",
    "NumberRealEstateLoansOrLines",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfDependents",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _code_revision() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return proc.stdout.strip()
    except Exception:
        return None


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "NA", "NaN", "null", "None"):
        return None
    return float(s)


def _parse_int(val: Any) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "NA", "NaN", "null", "None"):
        return None
    return int(float(s))


def run_credit_factory(
    csv_path: str | Path,
    output_dir: str | Path,
    *,
    load_to_db: bool = True,
    database_url: str | None = None,
    batch_size: int = 5000,
) -> dict[str, Any]:
    """Ingest, validate, quarantine, record manifest, and optionally load credit data into PostgreSQL."""
    started = datetime.now(UTC)
    source_file = Path(csv_path).resolve()
    if not source_file.is_file():
        raise FileNotFoundError(f"Source file not found: {source_file}")

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    curated_csv = out_dir / "curated_records.csv"
    quarantine_path = out_dir / "quarantine.jsonl"
    quality_path = out_dir / "quality_report.json"
    manifest_path = out_dir / "run_manifest.json"

    raw_count = 0
    accepted_count = 0
    quarantined_count = 0
    quarantine_by_reason: dict[str, int] = {}

    valid_rows: list[dict[str, Any]] = []

    with (
        source_file.open("r", encoding="utf-8-sig", newline="") as src_stream,
        curated_csv.open("w", encoding="utf-8", newline="") as cur_stream,
        quarantine_path.open("w", encoding="utf-8", newline="\n") as quar_stream,
    ):
        reader = csv.DictReader(src_stream)
        fieldnames_in_file = set(reader.fieldnames or ())
        if not set(CORE_CREDIT_COLUMNS).issubset(fieldnames_in_file):
            raise DataValidationError(f"Invalid columns in source credit CSV: {reader.fieldnames}")

        # ID column can be '' or 'Unnamed: 0' or 'id'
        id_col = None
        for candidate in ("", "Unnamed: 0", "id", "ID"):
            if candidate in fieldnames_in_file:
                id_col = candidate
                break

        out_fieldnames = [
            "applicant_id",
            "serious_dlqin_2yrs",
            "revolving_utilization_of_unsecured_lines",
            "age",
            "number_of_time30_59_days_past_due_not_worse",
            "debt_ratio",
            "monthly_income",
            "number_of_open_credit_lines_and_loans",
            "number_of_times90_days_late",
            "number_real_estate_loans_or_lines",
            "number_of_time60_89_days_past_due_not_worse",
            "number_of_dependents",
        ]
        writer = csv.DictWriter(cur_stream, fieldnames=out_fieldnames)
        writer.writeheader()

        for row in reader:
            raw_count += 1
            reason = None

            try:
                raw_id = row.get(id_col) if id_col is not None else None
                applicant_id = int(raw_id) if raw_id not in (None, "") else raw_count
                target = int(row["SeriousDlqin2yrs"])
                if target not in (0, 1):
                    reason = f"invalid_target_{target}"

                util = _parse_float(row["RevolvingUtilizationOfUnsecuredLines"])
                age = _parse_int(row["age"])
                if age is None or age < 0:
                    reason = "negative_or_missing_age"

                past_due_30_59 = _parse_int(row["NumberOfTime30-59DaysPastDueNotWorse"])
                debt_ratio = _parse_float(row["DebtRatio"])
                monthly_income = _parse_float(row["MonthlyIncome"])
                open_lines = _parse_int(row["NumberOfOpenCreditLinesAndLoans"])
                times_90_late = _parse_int(row["NumberOfTimes90DaysLate"])
                real_estate = _parse_int(row["NumberRealEstateLoansOrLines"])
                past_due_60_89 = _parse_int(row["NumberOfTime60-89DaysPastDueNotWorse"])
                dependents = _parse_int(row["NumberOfDependents"])

                if (
                    past_due_30_59 is None
                    or open_lines is None
                    or times_90_late is None
                    or real_estate is None
                    or past_due_60_89 is None
                ):
                    reason = "missing_mandatory_account_counts"
                elif open_lines < 0 or times_90_late < 0 or real_estate < 0:
                    reason = "negative_loan_or_late_count"

            except (ValueError, TypeError) as exc:
                reason = f"type_conversion_error_{exc.__class__.__name__}"

            if reason:
                quarantined_count += 1
                quarantine_by_reason[reason] = quarantine_by_reason.get(reason, 0) + 1
                quar_stream.write(json.dumps({"row_number": raw_count, "raw": row, "reason": reason}) + "\n")
            else:
                accepted_count += 1
                clean_record = {
                    "applicant_id": applicant_id,
                    "serious_dlqin_2yrs": target,
                    "revolving_utilization_of_unsecured_lines": util,
                    "age": age,
                    "number_of_time30_59_days_past_due_not_worse": past_due_30_59,
                    "debt_ratio": debt_ratio,
                    "monthly_income": monthly_income,
                    "number_of_open_credit_lines_and_loans": open_lines,
                    "number_of_times90_days_late": times_90_late,
                    "number_real_estate_loans_or_lines": real_estate,
                    "number_of_time60_89_days_past_due_not_worse": past_due_60_89,
                    "number_of_dependents": dependents,
                }
                writer.writerow(clean_record)
                if load_to_db:
                    valid_rows.append(clean_record)

    # Write quality report
    quality_report = {
        "raw_count": raw_count,
        "accepted_count": accepted_count,
        "quarantined_count": quarantined_count,
        "quarantine_ratio": round(quarantined_count / raw_count, 6) if raw_count else 0,
        "quarantine_by_reason": quarantine_by_reason,
    }
    quality_path.write_text(json.dumps(quality_report, indent=2), encoding="utf-8")

    db_stats = None
    if load_to_db:
        db_stats = load_credit_to_database(
            valid_rows,
            database_url=database_url,
            batch_size=batch_size,
        )

    finished = datetime.now(UTC)

    # Generate Manifest
    output_hashes = {
        p.name: _sha256(p) for p in [curated_csv, quarantine_path, quality_path] if p.is_file()
    }
    manifest = {
        "run_started_at_utc": started.isoformat(),
        "run_finished_at_utc": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "code_version": __version__,
        "code_revision": _code_revision(),
        "source_file": str(source_file),
        "source_file_sha256": _sha256(source_file),
        "raw_records": raw_count,
        "accepted_records": accepted_count,
        "quarantined_records": quarantined_count,
        "quarantine_by_reason": quarantine_by_reason,
        "database_destination": db_stats,
        "outputs_sha256": output_hashes,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "raw_records": raw_count,
        "accepted_records": accepted_count,
        "quarantined_records": quarantined_count,
        "manifest_path": str(manifest_path),
        "database": db_stats,
    }


def load_credit_to_database(
    records: list[dict[str, Any]],
    *,
    database_url: str | None = None,
    batch_size: int = 5000,
) -> dict[str, Any]:
    """Upsert validated credit records into PostgreSQL under credit.borrowers."""
    from sqlalchemy import create_engine, text

    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set")

    engine = create_engine(url, pool_pre_ping=True)

    # DDL for table and view
    ddl_schema = """
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
    """

    ddl_view = """
    CREATE OR REPLACE VIEW credit.vw_borrowers_clean AS
    SELECT
        applicant_id,
        serious_dlqin_2yrs,
        revolving_utilization_of_unsecured_lines,
        age,
        CASE 
            WHEN number_of_time30_59_days_past_due_not_worse IN (96, 98)
              OR number_of_time60_89_days_past_due_not_worse IN (96, 98)
              OR number_of_times90_days_late IN (96, 98)
            THEN TRUE ELSE FALSE
        END AS has_sentinel_late_code,
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
        CASE 
            WHEN number_of_time30_59_days_past_due_not_worse IN (96, 98) THEN NULL 
            ELSE (
                number_of_time30_59_days_past_due_not_worse + 
                number_of_time60_89_days_past_due_not_worse + 
                number_of_times90_days_late
            )
        END AS clean_total_past_due_events,
        CASE WHEN monthly_income IS NULL THEN TRUE ELSE FALSE END AS is_monthly_income_missing,
        CASE WHEN number_of_dependents IS NULL THEN TRUE ELSE FALSE END AS is_dependents_missing,
        CASE WHEN age < 18 THEN TRUE ELSE FALSE END AS is_impossible_age,
        CASE WHEN monthly_income IS NULL AND debt_ratio > 1.0 THEN TRUE ELSE FALSE END AS is_debt_ratio_as_dollar_amount,
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
    """

    statement = text("""
        INSERT INTO credit.borrowers
            (applicant_id, serious_dlqin_2yrs, revolving_utilization_of_unsecured_lines,
             age, number_of_time30_59_days_past_due_not_worse, debt_ratio,
             monthly_income, number_of_open_credit_lines_and_loans,
             number_of_times90_days_late, number_real_estate_loans_or_lines,
             number_of_time60_89_days_past_due_not_worse, number_of_dependents)
        VALUES
            (:applicant_id, :serious_dlqin_2yrs, :revolving_utilization_of_unsecured_lines,
             :age, :number_of_time30_59_days_past_due_not_worse, :debt_ratio,
             :monthly_income, :number_of_open_credit_lines_and_loans,
             :number_of_times90_days_late, :number_real_estate_loans_or_lines,
             :number_of_time60_89_days_past_due_not_worse, :number_of_dependents)
        ON CONFLICT (applicant_id) DO UPDATE SET
            serious_dlqin_2yrs = EXCLUDED.serious_dlqin_2yrs,
            revolving_utilization_of_unsecured_lines = EXCLUDED.revolving_utilization_of_unsecured_lines,
            age = EXCLUDED.age,
            number_of_time30_59_days_past_due_not_worse = EXCLUDED.number_of_time30_59_days_past_due_not_worse,
            debt_ratio = EXCLUDED.debt_ratio,
            monthly_income = EXCLUDED.monthly_income,
            number_of_open_credit_lines_and_loans = EXCLUDED.number_of_open_credit_lines_and_loans,
            number_of_times90_days_late = EXCLUDED.number_of_times90_days_late,
            number_real_estate_loans_or_lines = EXCLUDED.number_real_estate_loans_or_lines,
            number_of_time60_89_days_past_due_not_worse = EXCLUDED.number_of_time60_89_days_past_due_not_worse,
            number_of_dependents = EXCLUDED.number_of_dependents
    """)

    total_loaded = 0
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(ddl_schema)
            conn.exec_driver_sql(ddl_view)

            for i in range(0, len(records), batch_size):
                chunk = records[i : i + batch_size]
                conn.execute(statement, chunk)
                total_loaded += len(chunk)
    finally:
        engine.dispose()

    return {
        "destination_table": "credit.borrowers",
        "destination_view": "credit.vw_borrowers_clean",
        "rows_upserted": total_loaded,
        "mode": "idempotent_upsert",
    }
