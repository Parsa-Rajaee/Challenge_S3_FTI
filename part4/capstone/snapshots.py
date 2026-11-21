"""Load timestamped checkout snapshots supplied by a source that records them."""
import csv
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import text

FIELDS = ("order_id", "observed_at", "seller_count", "product_count",
          "observed_payment_value", "interstate_shipping")

def load_snapshots(engine, path):
    # Each record summarizes a complete basket as it existed at observed_at.
    # Never derive this timestamp from a later delivery or review.
    with engine.begin() as connection:
        connection.execute(text("""CREATE TABLE IF NOT EXISTS capstone.checkout_snapshots (
            order_id uuid NOT NULL, observed_at timestamp NOT NULL,
            seller_count integer NOT NULL, product_count integer NOT NULL,
            observed_payment_value numeric NOT NULL, interstate_shipping integer NOT NULL,
            PRIMARY KEY(order_id, observed_at)
        )"""))
        connection.execute(text("TRUNCATE capstone.checkout_snapshots"))
        if path is None:
            return
        with open(path, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if sorted(reader.fieldnames or []) != sorted(FIELDS):
                raise ValueError(f"Checkout snapshot schema mismatch. Expected {FIELDS}")
            for line, row in enumerate(reader, 2):
                try:
                    row["order_id"] = UUID(row["order_id"])
                    observed = datetime.fromisoformat(row["observed_at"])
                    if observed.tzinfo is not None:
                        raise ValueError("use the same local time convention as Olist")
                    row["observed_at"] = observed
                    for name in ("seller_count", "product_count", "interstate_shipping"):
                        row[name] = int(row[name])
                    value = Decimal(row["observed_payment_value"])
                    if not value.is_finite() or value < 0 or min(row["seller_count"], row["product_count"]) < 0:
                        raise ValueError("counts and observed payment value must be finite and nonnegative")
                    if row["interstate_shipping"] not in (0, 1):
                        raise ValueError("interstate_shipping must be 0 or 1")
                    row["observed_payment_value"] = value
                except (ValueError, TypeError, ArithmeticError) as error:
                    raise ValueError(f"Invalid checkout snapshot on line {line}: {error}") from error
                connection.execute(text("""INSERT INTO capstone.checkout_snapshots VALUES
                    (:order_id,:observed_at,:seller_count,:product_count,:observed_payment_value,:interstate_shipping)
                """), row)
