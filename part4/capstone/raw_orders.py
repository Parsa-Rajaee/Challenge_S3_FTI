"""Read an evaluator's Olist orders CSV using the ingestion field definitions."""
import csv
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from database_performance.schema import DATASETS
from .external import acquire_holidays

ROOT = Path(__file__).resolve().parents[1]

def feature_query(source):
    if source not in ("olist.orders", "incoming_orders"):
        raise ValueError("Unknown order source")
    template = (ROOT / "sql" / "order_features.sql").read_text(encoding="utf-8")
    return template.replace("{orders}", source)

def ensure_calendar(connection, years):
    holidays = acquire_holidays(years, ROOT / "data" / "external")
    for day, name, source in holidays:
        connection.execute(text("""
            INSERT INTO capstone.holidays VALUES (:day,:name,:source)
            ON CONFLICT (holiday_date) DO NOTHING
        """), {"day":day, "name":name, "source":source})

def raw_features(path, engine):
    contract = next(table for table in DATASETS if table.name == "orders")
    headers = [field.source_name for field in contract.fields]
    rows = []
    seen = set()
    years = set()
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if sorted(reader.fieldnames or []) != sorted(headers):
            raise ValueError(f"Input schema mismatch. Expected Olist orders columns {headers}")
        for line, raw in enumerate(reader, start=2):
            if None in raw:
                raise ValueError(f"Too many fields on row {line}")
            try:
                row = {field.name: field.parse(raw[field.source_name]) for field in contract.fields}
            except ValueError as error:
                raise ValueError(f"Row {line}: {error}") from error
            if row["order_id"] in seen:
                raise ValueError(f"Duplicate order_id on row {line}")
            seen.add(row["order_id"])
            if row["order_approved_at"] is not None:
                years.add(row["order_approved_at"].year)
                rows.append(row)
    with engine.begin() as connection:
        ensure_calendar(connection, years)
        connection.execute(text("""
            CREATE TEMP TABLE incoming_orders (
                order_id uuid PRIMARY KEY, customer_id uuid, order_purchase_timestamp timestamp,
                order_approved_at timestamp
            ) ON COMMIT DROP
        """))
        if rows:
            connection.execute(text("""
                INSERT INTO incoming_orders VALUES
                (:order_id,:customer_id,:order_purchase_timestamp,:order_approved_at)
            """), rows)
        query = feature_query("incoming_orders") + " ORDER BY approved_at, o.order_id"
        return pd.read_sql_query(text(query), connection)
