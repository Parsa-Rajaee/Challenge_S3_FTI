"""Offline guards for safe CSV loading behavior."""

import csv
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text

from database_performance.benchmark import Explain
from database_performance.loader import (
    ANALYZE_OLIST_SQL,
    REBUILD_SNAPSHOTS_SQL,
    TRUNCATE_OLIST_SQL,
    load_olist,
)
from database_performance.schema import DATASETS


class LoaderGuardTests(unittest.TestCase):
    def test_nonpositive_batch_size_is_rejected_before_database_access(self):
        with self.assertRaisesRegex(ValueError, "batch_size must be positive"):
            load_olist(None, ".", batch_size=0)

    def test_missing_source_files_are_reported_before_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "Missing Olist CSV files") as error:
                load_olist(None, directory)
        self.assertIn("olist_orders_dataset.csv", str(error.exception))
        self.assertIn("product_category_name_translation.csv", str(error.exception))

    def test_quarantine_is_published_after_its_file_handle_closes(self):
        class Connection:
            def execute(self, *args, **kwargs):
                return None

            def exec_driver_sql(self, *args, **kwargs):
                return None

        class Engine:
            @contextmanager
            def begin(self):
                yield Connection()

        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "data" / "raw"
            raw.mkdir(parents=True)
            for dataset in DATASETS:
                with (raw / dataset.filename).open("w", encoding="utf-8", newline="") as stream:
                    csv.writer(stream).writerow([field.source_name for field in dataset.fields])

            result = load_olist(Engine(), raw)

            quarantine = Path(result["quarantine_file"])
            self.assertTrue(quarantine.is_file())
            self.assertEqual(quarantine.read_text(encoding="utf-8"), "")
            self.assertEqual(list(quarantine.parent.glob(".olist-quarantine-*.tmp")), [])

    def test_load_sql_is_static_and_covers_every_olist_table(self):
        names = [dataset.name for dataset in DATASETS]
        for name in names:
            self.assertIn(f"olist.{name}", TRUNCATE_OLIST_SQL)
            self.assertIn(f"ANALYZE olist.{name};", ANALYZE_OLIST_SQL)
        self.assertIn("RESTART IDENTITY CASCADE", TRUNCATE_OLIST_SQL)
        self.assertIn("CALL analytics.rebuild_monthly_snapshot", REBUILD_SNAPSHOTS_SQL)

    def test_explain_compiles_options_without_python_string_concatenation_of_user_sql(self):
        compiled = str(
            Explain(text("SELECT 1"), analyze=True, buffers=True, format="JSON").compile(
                dialect=postgresql.dialect()
            )
        )
        self.assertTrue(compiled.startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"))
        self.assertIn("SELECT 1", compiled)


if __name__ == "__main__":
    unittest.main()
