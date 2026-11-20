"""Database connectivity and SQLAlchemy extraction for Stage 3 Credit Risk."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from .sentinel import LATE_COLUMNS, VIEW_RAW_COLUMNS, clean_sentinel_values


def get_db_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine connected to PostgreSQL."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        # Check if root or part3 .env exists
        for env_path in (Path(".env"), Path("../.env"), Path("../../.env")):
            if env_path.is_file():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("DATABASE_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
            if url:
                break
    if not url:
        url = "postgresql+psycopg2://season3:1234@localhost:5432/olist"
    return create_engine(url, pool_pre_ping=True)


def load_clean_borrowers(
    engine: Engine | None = None,
    limit: int | None = None,
    allow_curated_fallback: bool = True,
) -> pd.DataFrame:
    """Read the prepared dataset from database view credit.vw_borrowers_clean using SQLAlchemy.

    If the connection fails and fallback is enabled, derive model and audit fields
    from the curated CSV. Errors while querying a connected database propagate.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be nonnegative")
    eng = engine or get_db_engine()
    query = "SELECT * FROM credit.vw_borrowers_clean ORDER BY applicant_id"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    try:
        connection = eng.connect()
    except OperationalError:
        if not allow_curated_fallback:
            raise
        for candidate in (
            Path(__file__).resolve().parents[2] / "data" / "curated" / "curated_records.csv",
            Path("data/curated/curated_records.csv"),
            Path("part3/stage-3-machine-learning/data/curated/curated_records.csv"),
        ):
            if candidate.is_file():
                raw = pd.read_csv(candidate).sort_values("applicant_id", kind="stable")
                if limit is not None:
                    raw = raw.head(limit)
                return _prepare_curated_rows(raw.reset_index(drop=True))
        raise

    with connection:
        return pd.read_sql(text(query), connection)


def _prepare_curated_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Keep original late counts for auditing alongside the model's cleaned counts."""
    cleaned = clean_sentinel_values(raw)
    for source, alias in zip(LATE_COLUMNS, VIEW_RAW_COLUMNS):
        cleaned[alias] = raw[source]
    cleaned["is_monthly_income_missing"] = raw["monthly_income"].isna()
    cleaned["is_dependents_missing"] = raw["number_of_dependents"].isna()
    cleaned["is_impossible_age"] = raw["age"] < 18
    cleaned["is_debt_ratio_as_dollar_amount"] = raw["monthly_income"].isna() & (raw["debt_ratio"] > 1)
    return cleaned


def load_raw_borrowers(
    engine: Engine | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Read raw borrowers directly from credit.borrowers table using SQLAlchemy."""
    eng = engine or get_db_engine()
    query = "SELECT * FROM credit.borrowers ORDER BY applicant_id"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    with eng.connect() as conn:
        return pd.read_sql(text(query), conn)
