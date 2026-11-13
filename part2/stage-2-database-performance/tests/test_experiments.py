"""Offline guards for reproducible, bounded experiment setup."""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database_performance.benchmark import (
    benchmark_queries,
    benchmark_statement,
    measure_insert_cost,
)
from database_performance.experiments import plan_nodes, prepare_database
from database_performance.loader import apply_migrations
from database_performance.schema import DATASETS


class ExperimentGuardTests(unittest.TestCase):
    def test_missing_raw_inputs_fail_before_destructive_database_access(self):
        engine = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(FileNotFoundError, "Missing Olist inputs"):
                prepare_database(engine, root, root / "stage1.csv")
        engine.begin.assert_not_called()

    def test_missing_stage1_fails_before_destructive_database_access(self):
        engine = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for dataset in DATASETS:
                (root / dataset.filename).touch()
            with self.assertRaisesRegex(FileNotFoundError, "Stage 1 curated_records.csv"):
                prepare_database(engine, root, root / "missing.csv")
        engine.begin.assert_not_called()

    def test_benchmarks_reject_inadequate_repetitions_without_connecting(self):
        engine = Mock()
        with self.assertRaisesRegex(ValueError, "three repetitions"):
            benchmark_statement(engine, "SELECT 1", {}, repetitions=1)
        with self.assertRaisesRegex(ValueError, "three repetitions"):
            benchmark_queries(engine, date(2017, 1, 1), date(2018, 1, 1), repetitions=2)
        engine.connect.assert_not_called()

    def test_empty_time_window_is_rejected_without_connecting(self):
        engine = Mock()
        with self.assertRaisesRegex(ValueError, "precede"):
            benchmark_queries(engine, date(2017, 1, 1), date(2017, 1, 1))
        engine.connect.assert_not_called()

    def test_write_benchmark_requires_positive_rows_and_repeated_measurements(self):
        for kwargs in ({"rows": 0}, {"repetitions": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                measure_insert_cost(Mock(), **kwargs)

    def test_retirement_migrations_require_the_index_sequence(self):
        with self.assertRaisesRegex(ValueError, "complete index migration sequence"):
            apply_migrations(Mock(), include_retirements=True)

    def test_plan_traversal_preserves_index_and_heap_evidence(self):
        child = {"Node Type": "Index Only Scan", "Index Name": "cover", "Heap Fetches": 0}
        plan = {"Node Type": "Aggregate", "Plans": [child]}
        self.assertEqual(plan_nodes(plan), [plan, child])


if __name__ == "__main__":
    unittest.main()
