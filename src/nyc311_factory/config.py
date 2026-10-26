"""Configuration loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any

from .exceptions import ConfigurationError


# frozen=True: a loaded Settings object cannot be changed. To modify one, make a copy with dataclasses.replace().
@dataclass(frozen=True)
class Settings:
    """Validated settings for one immutable source-data slice."""

    api_endpoint: str
    start_date: date
    end_date: date
    complaint_type: str
    page_size: int
    retry_attempts: int
    retry_backoff_seconds: float
    request_method: str
    target_min_records: int
    raw_dir: Path
    checkpoint_path: Path
    selected_fields: tuple[str, ...]
    # Fields below have defaults, so the config file may leave them out.
    max_quarantine_ratio: float = 0.05
    output_dir: Path | None = None
    population_path: Path | None = None
    source_schema_endpoint: str | None = None
    expected_source_schema: dict[str, str] | None = None
    request_timeout_seconds: float = 60.0
    rolling_window_days: int = 30

    @property
    def source_signature(self) -> dict[str, Any]:
        """Return settings that determine the downloaded source rows."""
        # Saved in the checkpoint. If these change, the old downloads no longer match the run.
        return {
            "api_endpoint": self.api_endpoint,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "complaint_type": self.complaint_type,
            "page_size": self.page_size,
            "selected_fields": list(self.selected_fields),
        }


def load_settings(path: str | Path) -> Settings:
    """Load JSON settings and resolve data paths from the project root."""
    config_path = Path(path).resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"Cannot read config file {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {config_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError("The configuration root must be a JSON object")

    # The config file sits in config/, so its parent's parent is the project root.
    # All data paths in the config are relative to that root.
    project_root = config_path.parent.parent
    # Convert each JSON value to the right Python type. A missing or badly typed value raises ConfigurationError.
    try:
        start_date = date.fromisoformat(payload["start_date"])
        end_date = date.fromisoformat(payload["end_date"])
        page_size = int(payload["page_size"])
        retry_attempts = int(payload["retry_attempts"])
        backoff = float(payload["retry_backoff_seconds"])
        target_min_records = int(payload["target_min_records"])
        request_method = str(payload["request_method"]).upper()
        api_endpoint = str(payload["api_endpoint"]).strip()
        complaint_type = str(payload["complaint_type"]).strip()
        raw_dir = project_root / payload["raw_dir"]
        checkpoint_path = project_root / payload["checkpoint_path"]
        selected_fields = tuple(payload["selected_fields"])
        max_quarantine_ratio = float(payload.get("max_quarantine_ratio", 0.05))
        output_dir = project_root / payload.get("output_dir", "data/curated")
        population_path = project_root / payload.get(
            "population_path", "data/reference/zip_population.csv"
        )
        source_schema_endpoint = payload.get("source_schema_endpoint")
        expected_source_schema = payload.get("expected_source_schema")
        request_timeout_seconds = float(payload.get("request_timeout_seconds", 60))
        rolling_window_days = int(payload.get("rolling_window_days", 30))
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"Missing or invalid configuration value: {exc}") from exc

    # Range checks: each one rejects a setting that would cause problems later.
    if start_date >= end_date:
        raise ConfigurationError("start_date must be earlier than end_date")
    if not 1 <= page_size <= 50_000:
        raise ConfigurationError("page_size must be between 1 and 50000")
    if retry_attempts < 1:
        raise ConfigurationError("retry_attempts must be at least 1")
    if backoff < 0:
        raise ConfigurationError("retry_backoff_seconds cannot be negative")
    if target_min_records < 0:
        raise ConfigurationError("target_min_records cannot be negative")
    # isfinite rejects NaN and infinity, which would pass a plain range check.
    if not isfinite(max_quarantine_ratio) or not 0 <= max_quarantine_ratio <= 1:
        raise ConfigurationError("max_quarantine_ratio must be between 0 and 1")
    if not isfinite(request_timeout_seconds) or request_timeout_seconds <= 0:
        raise ConfigurationError("request_timeout_seconds must be positive")
    if rolling_window_days < 1:
        raise ConfigurationError("rolling_window_days must be at least 1")
    if request_method not in {"GET", "POST"}:
        raise ConfigurationError("request_method must be GET or POST")
    # Data is only fetched over HTTPS, so responses cannot be tampered with in transit.
    if not api_endpoint.startswith("https://"):
        raise ConfigurationError("api_endpoint must use HTTPS")
    if not complaint_type:
        raise ConfigurationError("complaint_type cannot be empty")
    if not selected_fields or len(set(selected_fields)) != len(selected_fields):
        raise ConfigurationError("selected_fields must be a non-empty unique list")
    required_fields = {"unique_key", "created_date"}
    if not required_fields.issubset(selected_fields):
        raise ConfigurationError("selected_fields must include unique_key and created_date")
    # The optional schema contract must describe exactly the selected fields.
    if expected_source_schema is not None:
        if not isinstance(expected_source_schema, dict) or not expected_source_schema:
            raise ConfigurationError("expected_source_schema must be a non-empty object")
        if set(expected_source_schema) != set(selected_fields):
            raise ConfigurationError(
                "expected_source_schema must define the type of every selected field"
            )
        if not source_schema_endpoint or not str(source_schema_endpoint).startswith("https://"):
            raise ConfigurationError(
                "source_schema_endpoint must be HTTPS when schema validation is enabled"
            )
        if any(not isinstance(value, str) or not value.strip() for value in expected_source_schema.values()):
            raise ConfigurationError("expected source schema types must be non-empty strings")
    elif source_schema_endpoint:
        raise ConfigurationError(
            "source_schema_endpoint requires expected_source_schema"
        )

    return Settings(
        api_endpoint=api_endpoint,
        start_date=start_date,
        end_date=end_date,
        complaint_type=complaint_type,
        page_size=page_size,
        retry_attempts=retry_attempts,
        retry_backoff_seconds=backoff,
        request_method=request_method,
        target_min_records=target_min_records,
        raw_dir=raw_dir,
        checkpoint_path=checkpoint_path,
        selected_fields=selected_fields,
        max_quarantine_ratio=max_quarantine_ratio,
        output_dir=output_dir,
        population_path=population_path,
        source_schema_endpoint=(str(source_schema_endpoint) if source_schema_endpoint else None),
        expected_source_schema=expected_source_schema,
        request_timeout_seconds=request_timeout_seconds,
        rolling_window_days=rolling_window_days,
    )
