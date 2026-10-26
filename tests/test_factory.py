"""Offline tests for factory orchestration and manifest generation."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from nyc311_factory.config import Settings
from nyc311_factory.factory import run_factory


class FactoryTests(unittest.TestCase):
    def test_offline_replay_writes_manifest_without_source_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = root / "data/raw/311"
            output_dir = root / "data/curated"
            population_path = root / "data/reference/zip_population.csv"
            raw_dir.mkdir(parents=True)
            population_path.parent.mkdir(parents=True)
            population_path.write_text(
                "zip_code,population,borough\n10001,1000,MANHATTAN\n",
                encoding="utf-8",
            )
            settings = Settings(
                api_endpoint="https://example.test/resource.json",
                start_date=date(2024, 1, 1),
                end_date=date(2025, 7, 1),
                complaint_type="HEAT/HOT WATER",
                page_size=2,
                retry_attempts=1,
                retry_backoff_seconds=0,
                request_method="GET",
                target_min_records=0,
                raw_dir=raw_dir,
                checkpoint_path=raw_dir / "checkpoint.json",
                selected_fields=("unique_key", "created_date"),
                output_dir=output_dir,
                population_path=population_path,
            )
            page = [
                {
                    "unique_key": "1",
                    "created_date": "2024-01-01T00:00:00Z",
                    "closed_date": "2024-01-02T00:00:00Z",
                    "agency": "HPD",
                    "complaint_type": "HEAT/HOT WATER",
                    "descriptor": "HEAT",
                    "incident_zip": "10001",
                    "borough": "MANHATTAN",
                }
            ]
            page_path = raw_dir / "page_000000000.json"
            page_path.write_text(json.dumps(page), encoding="utf-8")
            (raw_dir / "checkpoint.json").write_text(
                json.dumps(
                    {
                        "signature": settings.source_signature,
                        "next_offset": 1,
                        "raw_count": 1,
                        "complete": True,
                    }
                ),
                encoding="utf-8",
            )

            result = run_factory(settings, offline=True)

            self.assertEqual(result["raw_records"], 1)
            self.assertEqual(result["accepted_records"], 1)
            self.assertEqual(result["analytical_records"], 1)
            self.assertEqual(result["request_count"], 0)
            manifest_path = output_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_schema_validation"], "skipped_offline")
            self.assertIsNone(manifest["source_schema"])
            self.assertEqual(manifest["request_count"], 0)
            self.assertEqual(manifest["code_revision"], "unavailable (no Git commit found)")
            self.assertIn("data/raw/311/page_000000000.json", manifest["outputs_sha256"])
            self.assertIn("data/curated/quality_report.json", manifest["outputs_sha256"])

            first_hashes = manifest["outputs_sha256"]
            run_factory(settings, offline=True)
            repeated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(repeated_manifest["outputs_sha256"], first_hashes)


if __name__ == "__main__":
    unittest.main()
