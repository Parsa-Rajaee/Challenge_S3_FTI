"""Load timestamped checkout snapshots supplied by a source that records them."""
import csv
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

FIELDS = (
    "order_id", "observed_at", "seller_count", "product_count",
    "observed_payment_value", "interstate_shipping",
)
INSERT = text("""
    INSERT INTO capstone.checkout_snapshots
    VALUES (:order_id, :observed_at, :seller_count, :product_count,
            :observed_payment_value, :interstate_shipping)
""")


def parse_snapshot(row):
    if None in row or any(value is None for value in row.values()):
        raise ValueError("row width does not match header")
    row["order_id"] = UUID(row["order_id"])
    observed_at = datetime.fromisoformat(row["observed_at"])
    if observed_at.tzinfo is not None:
        raise ValueError("use the same local time convention as Olist")
    row["observed_at"] = observed_at
    for name in ("seller_count", "product_count", "interstate_shipping"):
        row[name] = int(row[name])
    payment_value = Decimal(row["observed_payment_value"])
    if not payment_value.is_finite() or payment_value < 0:
        raise ValueError("observed payment value must be finite and nonnegative")
    if min(row["seller_count"], row["product_count"]) < 0:
        raise ValueError("counts must be nonnegative")
    if row["interstate_shipping"] not in (0, 1):
        raise ValueError("interstate_shipping must be 0 or 1")
    row["observed_payment_value"] = payment_value
    return row


def load_snapshots(connection, path, *, preserve_existing=False):
    """Replace snapshots within the caller's transaction."""
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS capstone.checkout_snapshots (
            order_id uuid NOT NULL, observed_at timestamp NOT NULL,
            seller_count integer NOT NULL, product_count integer NOT NULL,
            observed_payment_value numeric NOT NULL, interstate_shipping integer NOT NULL,
            PRIMARY KEY(order_id, observed_at)
        )
    """))
    if path is None and preserve_existing:
        return
    connection.execute(text("TRUNCATE capstone.checkout_snapshots"))
    if path is None:
        return
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if sorted(reader.fieldnames or []) != sorted(FIELDS):
            raise ValueError(f"Checkout snapshot schema mismatch. Expected {FIELDS}")
        batch = []
        for line, row in enumerate(reader, 2):
            try:
                batch.append(parse_snapshot(row))
            except (ValueError, ArithmeticError) as error:
                raise ValueError(f"Invalid checkout snapshot on line {line}: {error}") from error
            if len(batch) == 1000:
                connection.execute(INSERT, batch)
                batch.clear()
        if batch:
            connection.execute(INSERT, batch)
