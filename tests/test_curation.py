"""Offline tests for schema validation and curated outputs."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from nyc311_factory.config import Settings
from nyc311_factory.curation import curate_raw_pages
from nyc311_factory.exceptions import DataValidationError


def make_settings(root: Path, max_quarantine_ratio: float = 1.0) -> Settings:
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
        selected_fields=("unique_key", "created_date", "closed_date"),
        max_quarantine_ratio=max_quarantine_ratio,
    )


def valid_record(**updates: object) -> dict[str, object]:
    return {
        "unique_key": "1",
        "created_date": "2024-01-01T00:00:00Z",
        "closed_date": "2024-01-02T12:00:00Z",
        "agency": " HPD ",
        "complaint_type": "HEAT/HOT WATER",
        "descriptor": "HEAT",
        "incident_zip": " 10001-1234 ",
        "borough": "Manhattan",
        **updates,
    }


def write_page(settings: Settings, records: list[object]) -> None:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    path = settings.raw_dir / "page_000000000.json"
    path.write_text(json.dumps(records), encoding="utf-8")


class CurationTests(unittest.TestCase):
    def test_curates_fields_and_derives_closure_days(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            write_page(settings, [valid_record()])

            result = curate_raw_pages(settings, root / "data/curated")
            rows = (root / "data/curated/curated_records.csv").read_text(
                encoding="utf-8"
            ).splitlines()

            self.assertEqual(result["accepted_records"], 1)
            self.assertIn("unique_key,created_date,closed_date", rows[0])
            self.assertTrue(rows[1].startswith("1,2024-01-01T00:00:00.000000Z"))
            self.assertTrue(rows[1].endswith(",10001,MANHATTAN,1.5"))
            self.assertEqual(result["quarantined_records"], 0)

            quality = result["column_quality"]
            self.assertEqual(quality["unique_key"]["distinct_count"], 1)
            self.assertEqual(quality["incident_zip"]["distinct_count"], 1)
            self.assertEqual(quality["closure_days"]["min"], 1.5)
            self.assertEqual(quality["closure_days"]["max"], 1.5)
            self.assertEqual(quality["closure_days"]["null_percentage"], 0.0)
            saved_report = json.loads(
                (root / "data/curated/quality_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved_report["column_quality"], quality)

    def test_open_case_and_invalid_zip_placeholders_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            write_page(
                settings,
                [
                    valid_record(
                        closed_date=None,
                        incident_zip=" 00000 ",
                        borough="Unspecified",
                    )
                ],
            )

            result = curate_raw_pages(settings, root / "data/curated")
            row = (root / "data/curated/curated_records.csv").read_text(
                encoding="utf-8"
            ).splitlines()[1]

            self.assertEqual(result["accepted_records"], 1)
            self.assertIn(",,,", row)
            self.assertTrue(row.endswith(",,,"))
            self.assertEqual(
                result["column_quality"]["closure_days"]["null_percentage"],
                100.0,
            )
            self.assertEqual(result["column_quality"]["borough"]["null_count"], 1)

    def test_invalid_records_are_quarantined_with_specific_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            write_page(
                settings,
                [
                    valid_record(unique_key="2", created_date="not-a-date"),
                    valid_record(
                        unique_key="3",
                        closed_date="2023-12-31T23:59:00Z",
                    ),
                ],
            )

            result = curate_raw_pages(settings, root / "data/curated")
            quarantine = [
                json.loads(line)
                for line in (root / "data/curated/quarantine.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

            self.assertEqual(result["accepted_records"], 0)
            self.assertEqual(
                [item["reason_code"] for item in quarantine],
                ["INVALID_CREATED_DATE", "CLOSED_BEFORE_CREATED"],
            )

    def test_first_valid_occurrence_wins_duplicate_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            write_page(settings, [valid_record(), valid_record(agency="OTHER")])

            result = curate_raw_pages(settings, root / "data/curated")
            quarantine = (root / "data/curated/quarantine.jsonl").read_text(
                encoding="utf-8"
            )

            self.assertEqual(result["accepted_records"], 1)
            self.assertEqual(result["quarantine_by_reason"], {"DUPLICATE_UNIQUE_KEY": 1})
            self.assertIn('"reason_code":"DUPLICATE_UNIQUE_KEY"', quarantine)

    def test_quarantine_ratio_above_limit_fails_without_replacing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root, max_quarantine_ratio=0.25)
            write_page(settings, [valid_record(), valid_record(created_date="bad")])
            output_dir = root / "data/curated"

            with self.assertRaises(DataValidationError):
                curate_raw_pages(settings, output_dir)

            self.assertEqual(list(output_dir.iterdir()), [])

    def test_unknown_borough_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            write_page(settings, [valid_record(borough="NOT A BOROUGH")])

            result = curate_raw_pages(settings, root / "data/curated")

            self.assertEqual(result["quarantine_by_reason"], {"INVALID_BOROUGH": 1})

    def test_repeated_runs_produce_identical_output_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            write_page(settings, [valid_record(), valid_record(unique_key="2")])
            first_dir = root / "first"
            second_dir = root / "second"

            curate_raw_pages(settings, first_dir)
            curate_raw_pages(settings, second_dir)

            for name in ("curated_records.csv", "quarantine.jsonl", "quality_report.json"):
                self.assertEqual(
                    (first_dir / name).read_bytes(),
                    (second_dir / name).read_bytes(),
                )

    def test_fails_when_raw_pages_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)

            with self.assertRaises(DataValidationError):
                curate_raw_pages(settings, root / "data/curated")


if __name__ == "__main__":
    unittest.main()
