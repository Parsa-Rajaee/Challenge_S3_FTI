"""Database connectivity and SQLAlchemy extraction for Stage 3 Credit Risk."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, create_engine, text


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
) -> pd.DataFrame:
    """Read the prepared dataset from database view credit.vw_borrowers_clean using SQLAlchemy."""
    eng = engine or get_db_engine()
    query = "SELECT * FROM credit.vw_borrowers_clean ORDER BY applicant_id"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    with eng.connect() as conn:
        return pd.read_sql(text(query), conn)


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
