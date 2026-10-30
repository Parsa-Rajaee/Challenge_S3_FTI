"""Scratch: measure SQL files with extra indexes created temporarily (dropped afterwards)."""

from __future__ import annotations

import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

FULL = {"start_date": date(2016, 9, 1), "end_date": date(2018, 11, 1)}
QUARTER = {"start_date": date(2017, 10, 1), "end_date": date(2018, 1, 1)}

TEST_INDEXES = {
    "t_orders_status_purchase": "CREATE INDEX t_orders_status_purchase ON olist.orders (order_status, order_purchase_timestamp) INCLUDE (order_id)",
    "t_items_cover": "CREATE INDEX t_items_cover ON olist.order_items (order_id) INCLUDE (product_id, price, freight_value, seller_id)",
    "t_products_cover": "CREATE INDEX t_products_cover ON olist.products (product_id) INCLUDE (product_category_name)",
    "t_items_seller": "CREATE INDEX t_items_seller ON olist.order_items (seller_id) INCLUDE (order_id, price)",
    "t_items_order_cover": "CREATE INDEX t_items_order_cover ON olist.order_items (order_id) INCLUDE (price, freight_value)",
    "t_pay_cover": "CREATE INDEX t_pay_cover ON olist.order_payments (order_id, payment_type, payment_installments) INCLUDE (payment_value)",
    "t_reviews_cover": "CREATE INDEX t_reviews_cover ON olist.order_reviews (order_id) INCLUDE (review_score)",
}


def measure(engine, path, params, reps=9):
    statement = text(Path(path).read_text(encoding="utf-8"))
    with engine.connect() as connection:
        connection.execute(statement, params).all()
        samples = []
        for _ in range(reps):
            started = time.perf_counter()
            connection.execute(statement, params).all()
            samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def main(names: list[str], paths: list[str]) -> None:
    engine = create_engine(os.environ["DATABASE_URL"], isolation_level="AUTOCOMMIT")
    try:
        for label, params in (("full", FULL), ("quarter", QUARTER)):
            for path in paths:
                print(f"[no extra index] {label:8s} {Path(path).name:28s} {measure(engine, path, params):8.1f} ms")
        with engine.connect() as connection:
            for name in names:
                connection.execute(text(TEST_INDEXES[name]))
            connection.execute(text("VACUUM (ANALYZE) olist.orders"))
            connection.execute(text("VACUUM (ANALYZE) olist.order_items"))
            connection.execute(text("VACUUM (ANALYZE) olist.products"))
            connection.execute(text("VACUUM (ANALYZE) olist.order_payments"))
            connection.execute(text("VACUUM (ANALYZE) olist.order_reviews"))
        try:
            for label, params in (("full", FULL), ("quarter", QUARTER)):
                for path in paths:
                    print(f"[+{','.join(names)}] {label:8s} {Path(path).name:28s} {measure(engine, path, params):8.1f} ms")
        finally:
            with engine.connect() as connection:
                for name in names:
                    connection.execute(text(f"DROP INDEX IF EXISTS olist.{name}"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1].split(","), sys.argv[2:])
