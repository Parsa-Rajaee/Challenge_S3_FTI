"""Optional PostgreSQL destination for the validated NYC 311 factory output."""

from __future__ import annotations

import csv
import os
from importlib.resources import files
from pathlib import Path
from typing import Any


def load_curated_to_database(
    csv_path: str | Path,
    *,
    database_url: str | None = None,
    batch_size: int = 2000,
) -> dict[str, Any]:
    """Upsert curated records into ``nyc311.service_requests`` transactionally."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError(
            "Database support is optional; install it with python -m pip install -e .[database]"
        ) from exc
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL to a PostgreSQL SQLAlchemy URL")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    ddl = files("nyc311_factory").joinpath("sql/001_destination.sql").read_text(encoding="utf-8")
    statement = text("""
        INSERT INTO nyc311.service_requests
            (unique_key, created_date, closed_date, agency, complaint_type,
             descriptor, incident_zip, borough, closure_days)
        VALUES
            (:unique_key, :created_date, :closed_date, :agency, :complaint_type,
             :descriptor, :incident_zip, :borough, :closure_days)
        ON CONFLICT (unique_key) DO UPDATE SET
            created_date = EXCLUDED.created_date, closed_date = EXCLUDED.closed_date,
            agency = EXCLUDED.agency, complaint_type = EXCLUDED.complaint_type,
            descriptor = EXCLUDED.descriptor, incident_zip = EXCLUDED.incident_zip,
            borough = EXCLUDED.borough, closure_days = EXCLUDED.closure_days
    """)
    engine = create_engine(url, pool_pre_ping=True)
    total = 0
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)
            with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                required = {
                    "unique_key", "created_date", "closed_date", "agency", "complaint_type",
                    "descriptor", "incident_zip", "borough", "closure_days",
                }
                if set(reader.fieldnames or ()) != required:
                    raise ValueError(f"Unexpected curated CSV headers in {csv_path}")
                pending: list[dict[str, Any]] = []
                for row in reader:
                    pending.append({
                        "unique_key": int(row["unique_key"]),
                        "created_date": row["created_date"],
                        "closed_date": row["closed_date"] or None,
                        "agency": row["agency"], "complaint_type": row["complaint_type"],
                        "descriptor": row["descriptor"] or None,
                        "incident_zip": row["incident_zip"] or None,
                        "borough": row["borough"] or None,
                        "closure_days": float(row["closure_days"]) if row["closure_days"] else None,
                    })
                    if len(pending) == batch_size:
                        connection.execute(statement, pending)
                        total += len(pending)
                        pending.clear()
                if pending:
                    connection.execute(statement, pending)
                    total += len(pending)
    finally:
        engine.dispose()
    return {"destination": "nyc311.service_requests", "source_rows": total, "mode": "idempotent_upsert"}
