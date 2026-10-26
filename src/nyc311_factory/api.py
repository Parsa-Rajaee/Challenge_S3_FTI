"""Small, testable Socrata client for chunked NYC 311 requests."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from .config import Settings
from .exceptions import DataValidationError, NetworkError


class SocrataClient:
    """Fetch stable pages from a Socrata resource using GET or POST."""

    def __init__(self, settings: Settings, session: Any | None = None) -> None:
        self.settings = settings
        # A requests.Session reuses connections; tests can pass in a fake session instead.
        self.session = session or requests.Session()
        # Counts every HTTP attempt, including retries. It is reported in the run manifest.
        self.request_count = 0
        # Socrata key ID/secret are sent as HTTP Basic auth. They come from the
        # environment so credentials never end up in committed config or outputs.
        key_id = os.environ.get("NYC311_API_KEY_ID")
        key_secret = os.environ.get("NYC311_API_KEY_SECRET")
        if key_id and key_secret:
            self.session.auth = (key_id, key_secret)

    def _base_params(self) -> dict[str, Any]:
        # Date range: the start day is included, the end day is excluded.
        start = self.settings.start_date.isoformat()
        end = self.settings.end_date.isoformat()
        # SQL-style escaping: a single quote inside the value is doubled.
        complaint = self.settings.complaint_type.replace("'", "''")
        where = (
            f"created_date >= '{start}T00:00:00' AND "
            f"created_date < '{end}T00:00:00' AND "
            f"complaint_type = '{complaint}'"
        )
        # $-prefixed parameters are Socrata's query language (SoQL).
        # The sort order is stable, so pages neither overlap nor skip rows.
        return {
            "$select": ",".join(self.settings.selected_fields),
            "$where": where,
            "$order": "created_date ASC, unique_key ASC",
        }

    def _request(
        self,
        params: dict[str, Any],
        *,
        endpoint: str | None = None,
        method: str | None = None,
    ) -> Any:
        # Remembers the most recent failure, so it can be reported if every attempt fails.
        last_error: Exception | None = None
        request_method = method or self.settings.request_method
        request_url = endpoint or self.settings.api_endpoint
        # Try up to retry_attempts times.
        for attempt in range(self.settings.retry_attempts):
            try:
                # Count every attempt, including retries, for the request budget.
                self.request_count += 1
                if request_method == "POST":
                    response = self.session.post(
                        request_url,
                        data=params,
                        timeout=self.settings.request_timeout_seconds,
                    )
                else:
                    response = self.session.get(
                        request_url,
                        params=params,
                        timeout=self.settings.request_timeout_seconds,
                    )
            except requests.RequestException as exc:
                last_error = exc
                retryable = True
            else:
                # 429 (rate limit) and 5xx are temporary, so they are retried.
                # Other 4xx errors are caused by the request itself and fail immediately.
                if response.status_code == 429 or response.status_code >= 500:
                    # Only the first 300 characters of the error body are kept, to keep messages short.
                    last_error = RuntimeError(
                        f"HTTP {response.status_code}: {response.text[:300]}"
                    )
                    retryable = True
                elif not 200 <= response.status_code < 300:
                    raise NetworkError(
                        f"HTTP {response.status_code}: {response.text[:300]}"
                    )
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise DataValidationError("API returned invalid JSON") from exc

            # Stop if the error is not worth retrying, or if this was the last attempt.
            if not retryable or attempt + 1 == self.settings.retry_attempts:
                break
            # Exponential backoff: wait 1x, 2x, 4x... the configured base delay.
            time.sleep(self.settings.retry_backoff_seconds * (2**attempt))

        # Reached only when every attempt failed with a temporary error.
        raise NetworkError(f"Request failed after retries: {last_error}") from last_error

    def fetch_page(self, offset: int) -> list[dict[str, Any]]:
        """Fetch and validate a single page; never accumulates other pages."""
        if offset < 0:
            raise ValueError("offset cannot be negative")
        # $limit is how many rows to return; $offset is how many rows to skip first.
        params = self._base_params()
        params["$limit"] = self.settings.page_size
        params["$offset"] = offset
        payload = self._request(params)
        if not isinstance(payload, list):
            raise DataValidationError("API response must be a JSON array")

        # A page larger than requested means the response does not match our query.
        if len(payload) > self.settings.page_size:
            raise DataValidationError(
                f"API returned {len(payload)} rows for page size {self.settings.page_size}"
            )

        required = {"unique_key", "created_date"}
        for row_number, row in enumerate(payload):
            if not isinstance(row, dict):
                raise DataValidationError(f"Record {row_number} is not a JSON object")
            # Without these two fields a row cannot be deduplicated or filtered later.
            missing = [field for field in required if not row.get(field)]
            if missing:
                raise DataValidationError(
                    f"Record {row_number} is missing required source fields: {missing}"
                )
        return payload

    def validate_source_schema(self) -> dict[str, str] | None:
        """Compare selected fields and their Socrata types with the configured contract."""
        # The schema check is optional; it runs only when both settings are configured.
        expected = self.settings.expected_source_schema
        endpoint = self.settings.source_schema_endpoint
        if expected is None or endpoint is None:
            return None

        # The metadata endpoint describes the dataset's columns and Socrata types.
        payload = self._request({}, endpoint=endpoint, method="GET")
        columns = payload.get("columns") if isinstance(payload, dict) else None
        if not isinstance(columns, list):
            raise DataValidationError("Source metadata has no valid columns list")

        # Build a {field_name: socrata_type} map from what the API reports.
        actual: dict[str, str] = {}
        for column in columns:
            if not isinstance(column, dict):
                continue
            field_name = column.get("fieldName")
            data_type = column.get("dataTypeName")
            if isinstance(field_name, str) and isinstance(data_type, str):
                actual[field_name] = data_type

        # Fields in the contract that the API no longer provides, and fields whose type changed.
        missing = sorted(set(expected) - set(actual))
        changed = {
            field: {"expected": expected[field], "actual": actual[field]}
            for field in expected.keys() & actual.keys()
            if expected[field] != actual[field]
        }
        if missing or changed:
            raise DataValidationError(
                f"Source schema drift detected; missing fields={missing}, "
                f"changed field types={changed}"
            )
        return {field: actual[field] for field in expected}

    def count_matching_records(self) -> int:
        """Ask Socrata for a count without downloading the matching records."""
        # Reuse the date and complaint filter, but ask only for a count.
        base_params = self._base_params()
        params = {
            "$select": "count(*) as record_count",
            "$where": base_params["$where"],
        }
        payload = self._request(params)
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
            or "record_count" not in payload[0]
        ):
            raise DataValidationError("API returned an invalid aggregate count")
        try:
            count = int(payload[0]["record_count"])
        except (TypeError, ValueError) as exc:
            raise DataValidationError("API record count is not an integer") from exc
        if count < 0:
            raise DataValidationError("API record count cannot be negative")
        return count
