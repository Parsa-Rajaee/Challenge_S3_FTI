"""PostgreSQL integration tests; migrate a dedicated EMPTY database first.

Set DATABASE_URL to that database. Existing Olist rows are an error, never grounds
for truncation: fixtures and injected failures are always rolled back.
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import column, create_engine, exists, select, table, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database_performance.benchmark import QUERY_DIR
from database_performance.schema import DATASETS

DATABASE_URL = os.environ.get("DATABASE_URL")


def require_empty_olist_database(connection):
    catalog = table("pg_tables", column("tablename"), column("schemaname"), schema="pg_catalog")
    tables = connection.execute(
        select(catalog.c.tablename)
        .where(catalog.c.schemaname == "olist")
        .order_by(catalog.c.tablename)
    ).scalars()
    populated = []
    for table_name in tables:
        statement = select(exists().select_from(table(table_name, schema="olist")))
        if connection.execute(statement).scalar_one():
            populated.append(f"olist.{table_name}")
    if populated:
        raise AssertionError(
            "PostgreSQL integration tests require an empty Olist database; "
            f"found existing rows in {', '.join(populated)}. "
            "Refusing to insert fixtures or modify existing data. "
            "Use a dedicated blank test database."
        )


class DatabaseIsolationGuardTests(unittest.TestCase):
    def _connection(self, tables, populated=()):
        connection = Mock(dialect=postgresql.dialect())
        metadata = Mock()
        metadata.scalars.return_value = iter(tables)
        results = [metadata]
        for table_name in tables:
            result = Mock()
            result.scalar_one.return_value = table_name in populated
            results.append(result)
        connection.execute.side_effect = results
        return connection

    def test_empty_olist_tables_are_allowed_without_writes(self):
        tables = [dataset.name for dataset in DATASETS]
        connection = self._connection(tables)
        require_empty_olist_database(connection)
        self.assertEqual(connection.execute.call_count, len(tables) + 1)
        for call in connection.execute.call_args_list:
            self.assertTrue(str(call.args[0]).lstrip().startswith("SELECT"))

    def test_rows_in_any_olist_table_are_rejected_even_without_orders(self):
        tables = [dataset.name for dataset in DATASETS]
        for table_name in tables:
            with self.subTest(table=table_name):
                connection = self._connection(tables, populated={table_name})
                with self.assertRaisesRegex(AssertionError, f"existing rows in olist.{table_name}"):
                    require_empty_olist_database(connection)
                self.assertEqual(connection.execute.call_count, len(tables) + 1)

    def test_unknown_olist_tables_are_checked_with_quoted_identifiers(self):
        connection = self._connection(['extra"table'], populated={'extra"table'})
        with self.assertRaisesRegex(AssertionError, "dedicated blank test database"):
            require_empty_olist_database(connection)
        statement = connection.execute.call_args.args[0]
        compiled = statement.compile(dialect=connection.dialect)
        self.assertIn('olist."extra""table"', str(compiled))

    def test_rejected_fixture_setup_cleans_up_without_inserting_rows(self):
        connection = self._connection(["customers"], populated={"customers"})
        case = PostgreSQLIntegrationTests("test_database_function_returns_calendar_day_difference")
        case.engine = Mock()
        case.engine.connect.return_value = connection
        try:
            with self.assertRaisesRegex(AssertionError, "existing rows in olist.customers"):
                case.setUp()
        finally:
            case.doCleanups()
        connection.begin.return_value.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()
        for call in connection.execute.call_args_list:
            self.assertTrue(str(call.args[0]).lstrip().startswith("SELECT"))


@unittest.skipUnless(DATABASE_URL, "set DATABASE_URL to run PostgreSQL integration tests")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert DATABASE_URL is not None
        cls.engine = create_engine(DATABASE_URL)
        cls.addClassCleanup(cls.engine.dispose)
        with cls.engine.connect() as connection:
            require_empty_olist_database(connection)

    def setUp(self):
        self.connection = self.engine.connect()
        self.addCleanup(self.connection.close)
        self.transaction = self.connection.begin()
        self.addCleanup(self.transaction.rollback)
        require_empty_olist_database(self.connection)
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

    def _execute(self, statement, params=None):
        return self.connection.execute(text(statement), params or {})

    def _query(self, filename):
        return self._execute((QUERY_DIR / filename).read_text(encoding="utf-8"), {
            "start_date": date(2017, 4, 1), "end_date": date(2017, 5, 1),
        }).mappings().all()

    def _add_seller(self):
        seller = str(uuid4())
        self._execute("""
            INSERT INTO olist.sellers VALUES (:id, '00123', 'another city', 'RJ')
        """, {"id": seller})
        return seller

    def _add_order(self, *, purchase="2017-04-03 10:00:00", status="delivered",
                   approved="2017-04-03 11:00:00", carrier="2017-04-07 11:00:00"):
        order = str(uuid4())
        self._execute("""
            INSERT INTO olist.orders
                (order_id, customer_id, order_status, order_purchase_timestamp,
                 order_approved_at, order_delivered_carrier_date,
                 order_delivered_customer_date, order_estimated_delivery_date)
            VALUES (:order, :customer, :status, :purchase, :approved, :carrier,
                    '2017-04-10 10:00:00', '2017-04-10 10:00:00')
        """, {"order": order, "customer": self.customer, "status": status,
              "purchase": purchase, "approved": approved, "carrier": carrier})
        return order

    def _add_item(self, order, sequence, price, *, freight=5, seller=None):
        self._execute("""
            INSERT INTO olist.order_items
                (order_id, order_item_id, product_id, seller_id,
                 shipping_limit_date, price, freight_value)
            VALUES (:order, :sequence, :product, :seller,
                    '2017-04-05 00:00:00', :price, :freight)
        """, {"order": order, "sequence": sequence, "product": self.products[0],
              "seller": seller or self.seller, "price": price, "freight": freight})

    def _add_payment(self, order, sequence, payment_type, installments, value):
        self._execute("""
            INSERT INTO olist.order_payments
                (order_id, payment_sequential, payment_type, payment_installments, payment_value)
            VALUES (:order, :sequence, :payment_type, :installments, :value)
        """, {"order": order, "sequence": sequence, "payment_type": payment_type,
              "installments": installments, "value": value})

    def _add_review(self, order, score):
        self._execute("""
            INSERT INTO olist.order_reviews
                (review_id, order_id, review_score, review_creation_date)
            VALUES (:review, :order, :score, '2017-04-15 00:00:00')
        """, {"review": str(uuid4()), "order": order, "score": score})

    def _payment_metrics(self):
        return {
            (row["payment_type"], row["payment_installments"]): (
                row["payment_rows"], row["order_group_count"],
                row["mean_paid_value"], row["mean_order_value"],
            )
            for row in self._query("05_payments.sql")
        }

    def _snapshot_rows(self):
        return self._execute("""
            SELECT month, category, revenue, order_count, average_order_value
            FROM analytics.monthly_category_snapshot ORDER BY month, category
        """).all()

    def test_isolation_guard_rejects_fixture_rows_without_modifying_them(self):
        before = self._execute("SELECT * FROM olist.orders ORDER BY order_id").all()
        with self.assertRaisesRegex(AssertionError, "Refusing to insert fixtures"):
            require_empty_olist_database(self.connection)
        self.assertEqual(
            self._execute("SELECT * FROM olist.orders ORDER BY order_id").all(), before
        )

    def test_monthly_revenue_counts_distinct_orders_and_uses_item_price(self):
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 1)})
        rows = self._query("01_monthly_revenue.sql")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["revenue"], 150)
        self.assertEqual(rows[0]["order_count"], 2)
        self.assertEqual(rows[0]["average_order_value"], 75)

    def test_monthly_revenue_counts_multi_item_orders_once_without_payment_review_fanout(self):
        self._add_item(self.orders[0], 2, 25, freight=99)
        self._add_payment(self.orders[0], 2, "credit_card", 2, 20)
        self._add_review(self.orders[0], 5)
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 1)})
        rows = self._query("01_monthly_revenue.sql")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "test category")
        self.assertEqual(rows[0]["revenue"], 175)
        self.assertEqual(rows[0]["order_count"], 2)
        self.assertEqual(rows[0]["average_order_value"], Decimal("87.5"))

    def test_monthly_revenue_reads_snapshot_until_explicit_rebuild(self):
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 1)})
        before = self._query("01_monthly_revenue.sql")
        self._add_item(self.orders[0], 2, 25)
        self.assertEqual(self._query("01_monthly_revenue.sql"), before)
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": date(2017, 4, 1)})
        rows = self._query("01_monthly_revenue.sql")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["revenue"], 175)
        self.assertEqual(rows[0]["order_count"], 2)
        self.assertEqual(rows[0]["average_order_value"], Decimal("87.5"))

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

    def test_top_sellers_weight_shared_multi_item_orders_and_reviews_once(self):
        other_seller = self._add_seller()
        other_order = self._add_order()
        self._add_item(self.orders[0], 2, 20)
        self._add_item(self.orders[0], 3, 30)
        self._add_item(self.orders[0], 4, 40, seller=other_seller)
        self._add_item(self.orders[0], 5, 60, seller=other_seller)
        self._add_item(other_order, 1, 80, seller=other_seller)
        self._add_review(self.orders[0], 5)
        self._add_review(other_order, 1)
        rows = self._query("04_top_sellers.sql")
        self.assertEqual([str(row["seller_id"]) for row in rows], [self.seller, other_seller])
        metrics = {
            str(row["seller_id"]): (
                row["revenue"], row["mean_preparation_days"], row["mean_review_score"]
            ) for row in rows
        }
        self.assertEqual(metrics[self.seller], (200, 1, 4))
        self.assertEqual(metrics[other_seller], (180, 2, 2))

    def test_top_seller_averages_reviews_per_order_not_per_review_row(self):
        self._add_review(self.orders[0], 3)
        self._add_review(self.orders[0], 5)
        row, = self._query("04_top_sellers.sql")
        self.assertEqual(row["revenue"], 150)
        self.assertEqual(row["mean_preparation_days"], 1)
        self.assertEqual(row["mean_review_score"], 4)

    def test_top_sellers_keep_orders_and_sellers_without_reviews(self):
        self._execute("DELETE FROM olist.order_reviews WHERE order_id = :order",
                      {"order": self.orders[0]})
        unreviewed_seller = self._add_seller()
        self._add_item(self.orders[0], 2, 25, seller=unreviewed_seller)
        rows = {str(row["seller_id"]): row for row in self._query("04_top_sellers.sql")}
        self.assertEqual(set(rows), {self.seller, unreviewed_seller})
        self.assertEqual(rows[self.seller]["revenue"], 150)
        self.assertEqual(rows[self.seller]["mean_preparation_days"], 1)
        self.assertEqual(rows[self.seller]["mean_review_score"], 5)
        self.assertEqual(rows[unreviewed_seller]["revenue"], 25)
        self.assertEqual(rows[unreviewed_seller]["mean_preparation_days"], 0)
        self.assertIsNone(rows[unreviewed_seller]["mean_review_score"])

    def test_top_sellers_limit_twenty_with_deterministic_revenue_ties(self):
        sellers = [self._add_seller() for _ in range(21)]
        for sequence, seller in enumerate(sellers, start=2):
            self._add_item(self.orders[0], sequence, 10, seller=seller)
        rows = self._query("04_top_sellers.sql")
        self.assertEqual(len(rows), 20)
        self.assertEqual([str(row["seller_id"]) for row in rows],
                         [self.seller, *sorted(sellers)[:19]])
        self.assertEqual(rows[0]["revenue"], 150)
        for row in rows[1:]:
            self.assertEqual(row["revenue"], 10)
            self.assertEqual(row["mean_preparation_days"], 0)
            self.assertEqual(row["mean_review_score"], 1)

    def test_top_sellers_filter_delivered_orders_and_half_open_purchase_range(self):
        excluded_seller = self._add_seller()
        for order in (
            self._add_order(status="canceled"),
            self._add_order(purchase="2017-03-31 23:59:59"),
            self._add_order(purchase="2017-05-01 00:00:00"),
        ):
            self._add_item(order, 1, 1000, seller=excluded_seller)
            self._add_review(order, 5)
        row, = self._query("04_top_sellers.sql")
        self.assertEqual(str(row["seller_id"]), self.seller)
        self.assertEqual(row["revenue"], 150)
        self.assertEqual(row["mean_preparation_days"], 1)
        self.assertEqual(row["mean_review_score"], 3)

    def test_payment_query_separates_payment_and_order_values(self):
        rows = self._query("05_payments.sql")
        self.assertEqual({row["payment_type"] for row in rows}, {"credit_card", "boleto"})
        card = next(row for row in rows if row["payment_type"] == "credit_card")
        self.assertEqual(card["mean_paid_value"], 110)
        self.assertEqual(card["mean_order_value"], 105)

    def test_payment_query_counts_repeated_rows_but_weights_each_order_group_once(self):
        self._execute("""
            UPDATE olist.order_payments SET payment_type = 'credit_card', payment_installments = 2
            WHERE order_id = :order
        """, {"order": self.orders[1]})
        self._add_payment(self.orders[0], 2, "credit_card", 2, 20)
        self._add_payment(self.orders[0], 3, "credit_card", 2, 30)
        self.assertEqual(self._payment_metrics(), {
            ("credit_card", 2): (4, 2, Decimal("107.5"), 80),
        })

    def test_payment_query_does_not_multiply_payments_by_item_count(self):
        self._add_item(self.orders[0], 2, 30, freight=3)
        self._add_item(self.orders[0], 3, 20, freight=2)
        self._add_payment(self.orders[0], 2, "credit_card", 2, 10)
        self.assertEqual(self._payment_metrics(), {
            ("credit_card", 2): (2, 1, 120, 160),
            ("boleto", 1): (1, 1, 55, 55),
        })

    def test_payment_query_keeps_distinct_method_and_installment_groups_per_order(self):
        self._add_payment(self.orders[0], 2, "credit_card", 1, 20)
        self._add_payment(self.orders[0], 3, "credit_card", 2, 10)
        self._add_payment(self.orders[0], 4, "voucher", 1, 5)
        self._add_payment(self.orders[0], 5, "voucher", 1, 15)
        self._add_payment(self.orders[1], 2, "credit_card", 2, 30)
        self._add_payment(self.orders[1], 3, "credit_card", 1, 60)
        self._add_payment(self.orders[1], 4, "voucher", 1, 10)
        self.assertEqual(self._payment_metrics(), {
            ("credit_card", 1): (2, 2, 40, 80),
            ("credit_card", 2): (3, 2, 75, 80),
            ("voucher", 1): (3, 2, 15, 80),
            ("boleto", 1): (1, 1, 55, 55),
        })

    def test_payment_query_keeps_null_no_item_baskets_and_excludes_them_from_average(self):
        no_items = self._add_order()
        self._add_payment(no_items, 1, "credit_card", 2, 40)
        self._add_payment(no_items, 2, "voucher", 1, 10)
        self._add_payment(no_items, 3, "voucher", 1, 5)
        self.assertEqual(self._payment_metrics(), {
            ("credit_card", 2): (2, 2, 75, 105),
            ("voucher", 1): (2, 1, 15, None),
            ("boleto", 1): (1, 1, 55, 55),
        })

    def test_payment_query_uses_half_open_purchase_range_without_delivery_filter(self):
        for purchase in ("2017-03-31 23:59:59", "2017-05-01 00:00:00"):
            order = self._add_order(purchase=purchase)
            self._add_payment(order, 1, "voucher", 1, 1000)
        canceled = self._add_order(purchase="2017-04-01 00:00:00", status="canceled")
        self._add_payment(canceled, 1, "debit_card", 1, 25)
        self.assertEqual(self._payment_metrics(), {
            ("credit_card", 2): (1, 1, 110, 105),
            ("boleto", 1): (1, 1, 55, 55),
            ("debit_card", 1): (1, 1, 25, None),
        })

    def test_database_function_is_strict_and_returns_null_for_either_null_argument(self):
        self.assertTrue(self._execute("""
            SELECT proisstrict FROM pg_catalog.pg_proc
            WHERE oid = 'analytics.delivery_delay_days(timestamp, timestamp)'::regprocedure
        """).scalar_one())
        for actual, promised in (
            (None, "2017-04-09 23:00:00"),
            ("2017-04-11 01:00:00", None),
            (None, None),
        ):
            with self.subTest(actual=actual, promised=promised):
                self.assertIsNone(self._execute("""
                    SELECT analytics.delivery_delay_days(
                        CAST(:actual AS timestamp), CAST(:promised AS timestamp)
                    )
                """, {"actual": actual, "promised": promised}).scalar_one())

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

    def test_snapshot_procedure_mid_insert_failure_restores_deleted_rows_and_other_months(self):
        month = date(2017, 4, 1)
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": month})
        self._execute("""
            INSERT INTO analytics.monthly_category_snapshot
                (month, category, revenue, order_count, average_order_value)
            VALUES ('2017-03-01', :category, 777, 1, 777)
        """, {"category": self.category})
        before = self._snapshot_rows()
        self._add_item(self.orders[0], 2, 25)
        trigger = "stage2_snapshot_insert_failure"

        # PostgreSQL rolls back both the injected DDL and the failed CALL at this
        # savepoint; the outer transaction still owns all fixtures and sentinels.
        with (
            self.assertRaisesRegex(DBAPIError, "injected snapshot insert failure after deletion") as error,
            self.connection.begin_nested(),
        ):
            self._execute("""
                CREATE FUNCTION pg_temp.stage2_snapshot_insert_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM analytics.monthly_category_snapshot WHERE month = NEW.month
                    ) THEN
                        RAISE EXCEPTION 'snapshot rows were not deleted before insertion';
                    END IF;
                    RAISE EXCEPTION 'injected snapshot insert failure after deletion';
                END;
                $$
            """)
            self._execute("""
                CREATE TRIGGER stage2_snapshot_insert_failure
                BEFORE INSERT ON analytics.monthly_category_snapshot
                FOR EACH ROW
                WHEN (NEW.month = DATE '2017-04-01' AND NEW.category = 'test category')
                EXECUTE FUNCTION pg_temp.stage2_snapshot_insert_failure()
            """)
            self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": month})

        self.assertEqual(getattr(error.exception.orig, "pgcode", None), "P0001")
        self.assertEqual(self._snapshot_rows(), before)
        self.assertFalse(self._execute("""
            SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger WHERE tgname = :trigger)
        """, {"trigger": trigger}).scalar_one())
        self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": month})
        after = self._snapshot_rows()
        self.assertEqual([row for row in after if row.month != month],
                         [row for row in before if row.month != month])
        rebuilt = [row for row in after if row.month == month]
        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0].revenue, 175)
        self.assertEqual(rebuilt[0].order_count, 2)
        self.assertEqual(rebuilt[0].average_order_value, Decimal("87.5"))

    def test_snapshot_procedure_rejects_non_month_start(self):
        for month in (date(2017, 4, 15), None):
            with self.subTest(month=month):
                before = self._snapshot_rows()
                with (
                    self.assertRaisesRegex(DBAPIError, "p_month must be the first day"),
                    self.connection.begin_nested(),
                ):
                    self._execute("CALL analytics.rebuild_monthly_snapshot(:month)", {"month": month})
                self.assertEqual(self._snapshot_rows(), before)


if __name__ == "__main__":
    unittest.main()
