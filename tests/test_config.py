"""Configuration validation tests."""

import json
import tempfile
import unittest
from pathlib import Path

from nyc311_factory import config
from nyc311_factory.exceptions import ConfigurationError


BASE_CONFIG = {
    "api_endpoint": "https://example.test/resource.json",
    "start_date": "2024-01-01",
    "end_date": "2025-07-01",
    "complaint_type": "HEAT/HOT WATER",
    "page_size": 10,
    "retry_attempts": 2,
    "retry_backoff_seconds": 0,
    "request_method": "GET",
    "target_min_records": 0,
    "raw_dir": "data/raw/test",
    "checkpoint_path": "data/raw/test/checkpoint.json",
    "selected_fields": ["unique_key", "created_date"],
}


class SettingsTests(unittest.TestCase):
    def load_payload(self, payload: dict) -> config.Settings:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir = root / "config"
            config_dir.mkdir()
            path = config_dir / "project.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return config.load_settings(path)

    def test_valid_config_resolves_paths_relative_to_project(self) -> None:
        settings = self.load_payload(BASE_CONFIG)
        self.assertEqual(settings.page_size, 10)
        self.assertEqual(settings.raw_dir.name, "test")
        self.assertEqual(settings.start_date.isoformat(), "2024-01-01")

    def test_rejects_non_increasing_date_range(self) -> None:
        payload = {**BASE_CONFIG, "end_date": "2024-01-01"}
        with self.assertRaises(ConfigurationError):
            self.load_payload(payload)

    def test_rejects_page_size_above_socrata_limit(self) -> None:
        payload = {**BASE_CONFIG, "page_size": 50001}
        with self.assertRaises(ConfigurationError):
            self.load_payload(payload)

    def test_rejects_unknown_http_method(self) -> None:
        payload = {**BASE_CONFIG, "request_method": "PATCH"}
        with self.assertRaises(ConfigurationError):
            self.load_payload(payload)

    def test_requires_source_key_and_timestamp(self) -> None:
        payload = {**BASE_CONFIG, "selected_fields": ["unique_key"]}
        with self.assertRaises(ConfigurationError):
            self.load_payload(payload)

    def test_rejects_non_https_endpoint(self) -> None:
        payload = {**BASE_CONFIG, "api_endpoint": "http://example.test/resource.json"}
        with self.assertRaises(ConfigurationError):
            self.load_payload(payload)

    def test_rejects_quarantine_ratio_outside_zero_to_one(self) -> None:
        payload = {**BASE_CONFIG, "max_quarantine_ratio": 1.01}
        with self.assertRaises(ConfigurationError):
            self.load_payload(payload)


if __name__ == "__main__":
    unittest.main()
