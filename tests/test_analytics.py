"""Offline tests for population validation and analytical outputs."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from nyc311_factory.analytics import build_analysis_outputs, load_population
from nyc311_factory.config import Settings
from nyc311_factory.exceptions import DataValidationError


def make_settings(root: Path) -> Settings:
    return Settings(
        api_endpoint="https://example.test/resource.json",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 7, 1),
        complaint_type="HEAT/HOT WATER",
        page_size=2,
        retry_attempts=1,
        retry_backoff_seconds=0,
        request_method="GET",
        target_min_records=0,
        raw_dir=root / "data/raw/311",
        checkpoint_path=root / "data/raw/311/checkpoint.json",
        selected_fields=("unique_key", "created_date"),
    )


def curated_records() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "unique_key": "1",
                "created_date": "2024-01-01T00:00:00Z",
                "closed_date": "2024-01-01T00:00:00Z",
                "incident_zip": "10001",
                "borough": "BRONX",
                "closure_days": 0.0,
            },
            {
                "unique_key": "2",
                "created_date": "2024-01-15T00:00:00Z",
                "closed_date": "2024-01-17T00:00:00Z",
                "incident_zip": "10002",
                "borough": "BRONX",
                "closure_days": 2.0,
            },
            {
                "unique_key": "3",
                "created_date": "2024-02-01T00:00:00Z",
                "closed_date": "2024-02-05T00:00:00Z",
                "incident_zip": "11201",
                "borough": "BROOKLYN",
                "closure_days": 4.0,
            },
            {
                "unique_key": "4",
                "created_date": "2024-02-02T00:00:00Z",
                "closed_date": "",
                "incident_zip": "99999",
                "borough": "BROOKLYN",
                "closure_days": "",
            },
            {
                "unique_key": "5",
                "created_date": "2024-01-20T00:00:00Z",
                "closed_date": "2024-01-21T00:00:00Z",
                "incident_zip": "10001",
                "borough": "QUEENS",
                "closure_days": 1.0,
            },
            {
                "unique_key": "6",
                "created_date": "2024-03-01T00:00:00Z",
                "closed_date": "",
                "incident_zip": "10001",
                "borough": "",
                "closure_days": "",
            },
        ]
    )


def population_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "zip_code": ["10001", "10002", "11201"],
            "population": [1000, 2000, 4000],
            "borough": ["BRONX", "BRONX", "BROOKLYN"],
        }
    )


class AnalyticsTests(unittest.TestCase):
    def test_population_loader_preserves_zip_strings_and_normalizes_borough(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "population.csv"
            path.write_text(
                "zip_code,population,borough\n01001,12, bronx \n",
                encoding="utf-8",
            )

            population = load_population(path)

            self.assertEqual(population.loc[0, "zip_code"], "01001")
            self.assertEqual(population.loc[0, "population"], 12)
            self.assertEqual(population.loc[0, "borough"], "BRONX")

    def test_population_loader_rejects_duplicate_zip_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "population.csv"
            path.write_text(
                "zip_code,population,borough\n10001,10,BRONX\n10001,20,BRONX\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(DataValidationError, "duplicate ZIP"):
                load_population(path)

    def test_join_preserves_rows_and_reports_population_quality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curated_path = root / "curated_records.csv"
            output_dir = root / "output"
            curated_records().to_csv(curated_path, index=False)

            result = build_analysis_outputs(
                make_settings(root),
                curated_path,
                population_table(),
                output_dir,
            )

            self.assertEqual(result["source_records"], 6)
            self.assertEqual(result["analytical_records"], 6)
            self.assertEqual(result["population_matched_records"], 5)
            self.assertEqual(result["population_unmatched_records"], 1)
            self.assertEqual(result["borough_disagreements"], 1)
            self.assertEqual(result["monthly_summary_rows"], 4)

            analytical = pd.read_csv(
                output_dir / "analytical_records.csv", dtype={"unique_key": str}
            )
            self.assertEqual(len(analytical), 6)
            self.assertEqual(analytical["unique_key"].tolist(), ["1", "2", "3", "4", "5", "6"])
            self.assertFalse(bool(analytical.loc[3, "population_matched"]))
            self.assertTrue(pd.isna(analytical.loc[3, "population"]))

            summary = pd.read_csv(output_dir / "monthly_summary_wide.csv", index_col="borough")
            self.assertEqual(summary.loc["BRONX", "count_2024-01"], 2)
            self.assertEqual(summary.loc["BRONX", "median_closure_days_2024-01"], 1.0)
            self.assertAlmostEqual(
                summary.loc["BRONX", "rate_per_10k_2024-01"], 2 / 3000 * 10_000
            )
            self.assertEqual(summary.loc["BROOKLYN", "count_2024-02"], 2)
            self.assertEqual(summary.loc["BROOKLYN", "median_closure_days_2024-02"], 4.0)
            self.assertAlmostEqual(summary.loc["BROOKLYN", "rate_per_10k_2024-02"], 5.0)
            self.assertTrue(pd.isna(summary.loc["QUEENS", "rate_per_10k_2024-01"]))
            self.assertIn("MISSING_BOROUGH", summary.index)

    def test_analysis_rejects_missing_curated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(DataValidationError, "run curation first"):
                build_analysis_outputs(
                    make_settings(root),
                    root / "missing.csv",
                    population_table(),
                    root / "output",
                )


if __name__ == "__main__":
    unittest.main()
