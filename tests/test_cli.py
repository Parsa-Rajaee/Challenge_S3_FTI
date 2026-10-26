"""Offline tests for CLI mode compatibility."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import date, timedelta
from pathlib import Path

from nyc311_factory.cli import _rolling_settings, _write_rolling_state, main
from nyc311_factory.config import load_settings
from nyc311_factory.exceptions import DataValidationError


class CliTests(unittest.TestCase):
    def write_config(self, root: Path) -> Path:
        config_dir = root / "config"
        config_dir.mkdir()
        config_path = config_dir / "project.json"
        config_path.write_text(
            json.dumps(
                {
                    "api_endpoint": "https://example.test/resource.json",
                    "start_date": "2024-01-01",
                    "end_date": "2025-07-01",
                    "complaint_type": "HEAT/HOT WATER",
                    "page_size": 2,
                    "retry_attempts": 1,
                    "retry_backoff_seconds": 0,
                    "request_method": "GET",
                    "target_min_records": 0,
                    "raw_dir": "data/raw/311",
                    "checkpoint_path": "data/raw/311/checkpoint.json",
                    "selected_fields": ["unique_key", "created_date"],
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def test_first_rolling_window_uses_requested_lookback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(self.write_config(Path(directory)))

            rolling_settings, (state_path, end_date) = _rolling_settings(settings, 7)

            self.assertEqual(rolling_settings.end_date, end_date)
            self.assertEqual((end_date - rolling_settings.start_date).days, 7)
            self.assertEqual(rolling_settings.target_min_records, 0)
            self.assertFalse(state_path.exists())

    def test_rolling_window_resumes_from_previous_end_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(self.write_config(Path(directory)))
            previous_end = date.today() - timedelta(days=10)
            state_path = settings.raw_dir.parent / "rolling_state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps({"last_end_date": previous_end.isoformat()}),
                encoding="utf-8",
            )

            rolling_settings, _ = _rolling_settings(settings, 7)

            self.assertEqual(rolling_settings.start_date, previous_end)
            self.assertGreater(rolling_settings.end_date, previous_end)

    def test_corrupt_rolling_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(self.write_config(Path(directory)))
            state_path = settings.raw_dir.parent / "rolling_state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(DataValidationError, "Cannot use rolling-window state"):
                _rolling_settings(settings, 7)

    def test_rolling_state_writes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rolling_state.json"
            last_end_date = date(2025, 1, 1)

            _write_rolling_state(path, last_end_date)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"last_end_date": "2025-01-01"},
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_offline_mode_rejects_individual_pipeline_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self.write_config(Path(directory))
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["--config", str(config_path), "--offline", "--count-only"]
                )

            self.assertEqual(exit_code, 4)
            self.assertIn("only be used with the full factory", stderr.getvalue())

    def test_offline_mode_rejects_rolling_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self.write_config(Path(directory))
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--config",
                        str(config_path),
                        "--offline",
                        "--rolling-window-days",
                        "7",
                    ]
                )

            self.assertEqual(exit_code, 4)
            self.assertIn("cannot be combined with rolling-window", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
