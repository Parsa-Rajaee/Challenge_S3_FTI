"""PostgreSQL integration tests; set DATABASE_URL and run init-db first."""

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database_performance.benchmark import QUERY_DIR

DATABASE_URL = os.environ.get("DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "set DATABASE_URL to run PostgreSQL integration tests")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(DATABASE_URL)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        suffix = str(uuid4())
        self.customer = str(uuid4())
        self.seller = str(uuid4())
        self.category = "test_" + suffix
        self.orders = [str(uuid4()), str(uuid4())]
        self._execute("""
            INSERT INTO olist.category_translations VALUES (:category, :english)
        """, {"category": self.category, "english": "test category"})
        self._execute("""
            INSERT INTO olist.customers VALUES (:id, :unique_id, '00123', 'test city', 'SP')
        """, {"id": self.customer, "unique_id": str(uuid4())})
        self._execute("""
            INSERT INTO olist.sellers VALUES (:id, '00123', 'test city', 'SP')
        """, {"id": self.seller})
        self.products = [str(uuid4()), str(uuid4())]
        for product in self.products:
            self._execute("""
                INSERT INTO olist.products (product_id, product_category_name)
                VALUES (:id, :category)
            """, {"id": product, "category": self.category})
        for i, order in enumerate(self.orders):
            self._execute("""
                INSERT INTO olist.orders
                    (order_id, customer_id, order_status, order_purchase_timestamp,
                     order_approved_at, order_delivered_carrier_date,
                     order_delivered_customer_date, order_estimated_delivery_date)
                VALUES (:id, :customer, 'delivered', :purchase, :approved,
                        :carrier, :delivered, :estimated)
            """, {
                "id": order, "customer": self.customer,
                "purchase": f"2017-04-0{i + 1} 10:00:00",
                "approved": f"2017-04-0{i + 1} 11:00:00",
                "carrier": f"2017-04-0{i + 1 + i * 2} 11:00:00",
                "delivered": "2017-04-11 10:00:00" if i == 0 else "2017-04-10 10:00:00",
                "estimated": "2017-04-09 10:00:00" if i == 0 else "2017-04-10 10:00:00",
            })
            self._execute("""
                INSERT INTO olist.order_items
                    (order_id, order_item_id, product_id, seller_id, shipping_limit_date, price, freight_value)
                VALUES (:order, 1, :product, :seller, '2017-04-05 00:00:00', :price, 5.00)
            """, {"order": order, "product": self.products[i], "seller": self.seller,
                  "price": 100 if i == 0 else 50})
            self._execute("""
                INSERT INTO olist.order_reviews
                    (review_id, order_id, review_score, review_creation_date)
                VALUES (:review, :order, :score, '2017-04-15 00:00:00')
            """, {"review": str(uuid4()), "order": order, "score": 1 if i == 0 else 5})
            self._execute("""
                INSERT INTO olist.order_payments
                    (order_id, payment_sequential, payment_type, payment_installments, payment_value)
                VALUES (:order, 1, :payment_type, :installments, :value)
            """, {"order": order, "payment_type": "credit_card" if i == 0 else "boleto",
                  "installments": 2 if i == 0 else 1, "value": 110 if i == 0 else 55})

    def tearDown(self):
        self.transaction.rollback()
        self.connection.close()

    def _execute(self, statement, params=None):
        return self.connection.execute(text(statement), params or {})

    def _query(self, filename):
        return self._execute((QUERY_DIR / filename).read_text(encoding="utf-8"), {
            "start_date": date(2017, 4, 1), "end_date": date(2017, 5, 1),
        }).mappings().all()

    def test_monthly_revenue_counts_distinct_orders_and_uses_item_price(self):
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 1)})
        rows = self._query("01_monthly_revenue.sql")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["revenue"], 150)
        self.assertEqual(rows[0]["order_count"], 2)
        self.assertEqual(rows[0]["average_order_value"], 75)

    def test_late_delivery_ratio_is_one_half_for_fixture_state(self):
        rows = self._query("02_late_delivery.sql")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer_state"], "SP")
        self.assertEqual(float(rows[0]["late_share"]), 0.5)

    def test_delay_review_query_keeps_distinct_delay_groups(self):
        rows = self._query("03_delay_reviews.sql")
        scores = {row["delivery_bucket"]: float(row["mean_review_score"]) for row in rows}
        self.assertEqual(scores["late_1_7_days"], 1)
        self.assertEqual(scores["on_time"], 5)

    def test_top_seller_aggregates_revenue_preparation_and_reviews(self):
        rows = self._query("04_top_sellers.sql")
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["seller_id"]), self.seller)
        self.assertEqual(rows[0]["revenue"], 150)
        self.assertEqual(float(rows[0]["mean_review_score"]), 3)

    def test_payment_query_separates_payment_and_order_values(self):
        rows = self._query("05_payments.sql")
        self.assertEqual({row["payment_type"] for row in rows}, {"credit_card", "boleto"})
        card = next(row for row in rows if row["payment_type"] == "credit_card")
        self.assertEqual(card["mean_paid_value"], 110)
        self.assertEqual(card["mean_order_value"], 105)

    def test_database_function_returns_calendar_day_difference(self):
        row = self._execute("""
            SELECT analytics.delivery_delay_days(
                '2017-04-11 01:00:00'::timestamp, '2017-04-09 23:00:00'::timestamp
            ) AS days
        """).mappings().one()
        self.assertEqual(row["days"], 2)

    def test_snapshot_procedure_is_idempotent_for_one_month(self):
        for _ in range(2):
            self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 1)})
        rows = self._execute("""
            SELECT category, revenue, order_count, average_order_value
            FROM analytics.monthly_category_snapshot WHERE month = :month
        """, {"month": date(2017, 4, 1)}).mappings().all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["order_count"], 2)
        self.assertEqual(rows[0]["revenue"], 150)

    def test_snapshot_procedure_rejects_non_month_start(self):
        with self.assertRaises(DBAPIError):
            self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 15)})


if __name__ == "__main__":
    unittest.main()
