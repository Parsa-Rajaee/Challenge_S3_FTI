"""Offline tests for page persistence and resume behavior."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from nyc311_factory.config import Settings
from nyc311_factory.exceptions import CheckpointError, DataValidationError
from nyc311_factory.pipeline import RawDownloader


def make_settings(root: Path, target: int = 0) -> Settings:
    return Settings(
        api_endpoint="https://example.test/resource.json",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 7, 1),
        complaint_type="HEAT/HOT WATER",
        page_size=2,
        retry_attempts=1,
        retry_backoff_seconds=0,
        request_method="GET",
        target_min_records=target,
        raw_dir=root / "data/raw/311",
        checkpoint_path=root / "data/raw/311/checkpoint.json",
        selected_fields=("unique_key", "created_date"),
    )


class RawDownloaderTests(unittest.TestCase):
    def test_writes_pages_and_completes_on_short_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            client = Mock()
            client.fetch_page.side_effect = [
                [
                    {"unique_key": "1", "created_date": "2024-01-01"},
                    {"unique_key": "2", "created_date": "2024-01-02"},
                ],
                [{"unique_key": "3", "created_date": "2024-01-03"}],
            ]
            result = RawDownloader(settings, client).run()
            self.assertTrue(result["complete"])
            self.assertEqual(result["raw_count"], 3)
            self.assertTrue((settings.raw_dir / "page_000000000.json").is_file())
            self.assertTrue((settings.raw_dir / "page_000000002.json").is_file())

    def test_resume_starts_at_checkpoint_offset_without_rewriting_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            first_client = Mock()
            first_client.fetch_page.return_value = [
                {"unique_key": "1", "created_date": "2024-01-01"},
                {"unique_key": "2", "created_date": "2024-01-02"},
            ]
            downloader = RawDownloader(settings, first_client)
            settings.raw_dir.mkdir(parents=True)
            downloader._write_page(
                0,
                first_client.fetch_page.return_value,
            )
            downloader._write_checkpoint({
                "signature": settings.source_signature,
                "next_offset": 2,
                "raw_count": 2,
                "complete": False,
            })
            resume_client = Mock()
            resume_client.fetch_page.side_effect = [
                [{"unique_key": "3", "created_date": "2024-01-03"}],
            ]
            result = RawDownloader(settings, resume_client).run()
            self.assertEqual(resume_client.fetch_page.call_args.args[0], 2)
            self.assertEqual(result["raw_count"], 3)

    def test_completed_run_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            client = Mock()
            client.fetch_page.return_value = [
                {"unique_key": "1", "created_date": "2024-01-01"},
            ]
            first = RawDownloader(settings, client).run()
            client.fetch_page.reset_mock()
            second = RawDownloader(settings, client).run()
            self.assertEqual(first, second)
            client.fetch_page.assert_not_called()

    def test_offline_replay_uses_complete_checkpoint_without_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            client = Mock()
            client.validate_source_schema.side_effect = AssertionError("schema request made")
            client.fetch_page.side_effect = AssertionError("data request made")
            downloader = RawDownloader(settings, client)
            settings.raw_dir.mkdir(parents=True)
            downloader._write_page(
                0,
                [{"unique_key": "1", "created_date": "2024-01-01"}],
            )
            downloader._write_checkpoint(
                {
                    "signature": settings.source_signature,
                    "next_offset": 1,
                    "raw_count": 1,
                    "complete": True,
                }
            )

            result = downloader.run(offline=True)

            self.assertTrue(result["complete"])
            self.assertEqual(result["raw_count"], 1)
            self.assertIsNone(downloader.source_schema)
            client.validate_source_schema.assert_not_called()
            client.fetch_page.assert_not_called()

    def test_offline_replay_requires_complete_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            client = Mock()

            with self.assertRaisesRegex(CheckpointError, "complete raw download"):
                RawDownloader(settings, client).run(offline=True)

            client.validate_source_schema.assert_not_called()
            client.fetch_page.assert_not_called()

    def test_rejects_checkpoint_for_different_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(root)
            settings.raw_dir.mkdir(parents=True)
            settings.checkpoint_path.write_text(
                json.dumps({"signature": {}, "next_offset": 0, "raw_count": 0, "complete": False}),
                encoding="utf-8",
            )
            with self.assertRaises(CheckpointError):
                RawDownloader(settings, Mock()).run()

    def test_enforces_minimum_record_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory), target=2)
            client = Mock()
            client.fetch_page.return_value = [
                {"unique_key": "1", "created_date": "2024-01-01"},
            ]
            with self.assertRaises(DataValidationError):
                RawDownloader(settings, client).run()
            client.fetch_page.reset_mock()
            with self.assertRaises(DataValidationError):
                RawDownloader(settings, client).run()
            client.fetch_page.assert_not_called()

    def test_rejects_checkpoint_when_page_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            settings.raw_dir.mkdir(parents=True)
            settings.checkpoint_path.write_text(
                json.dumps({
                    "signature": settings.source_signature,
                    "next_offset": 2,
                    "raw_count": 2,
                    "complete": False,
                }),
                encoding="utf-8",
            )
            with self.assertRaises(CheckpointError):
                RawDownloader(settings, Mock()).run()


if __name__ == "__main__":
    unittest.main()
