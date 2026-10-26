"""Offline tests for CLI mode compatibility."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from nyc311_factory.cli import main


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
