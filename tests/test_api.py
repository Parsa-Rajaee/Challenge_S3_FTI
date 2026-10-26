"""Offline tests for the Socrata HTTP boundary."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from nyc311_factory.api import SocrataClient
from nyc311_factory.config import Settings
from nyc311_factory.exceptions import DataValidationError, NetworkError


def make_settings(method: str = "GET") -> Settings:
    root = Path(tempfile.gettempdir())
    return Settings(
        api_endpoint="https://example.test/resource.json",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 7, 1),
        complaint_type="HEAT/HOT WATER",
        page_size=2,
        retry_attempts=2,
        retry_backoff_seconds=0,
        request_method=method,
        target_min_records=0,
        raw_dir=root / "raw",
        checkpoint_path=root / "raw/checkpoint.json",
        selected_fields=("unique_key", "created_date", "closed_date"),
    )


def response(status: int, payload: object, text: str = "") -> Mock:
    result = Mock()
    result.status_code = status
    result.text = text
    result.json.return_value = payload
    return result


class SocrataClientTests(unittest.TestCase):
    def test_get_sends_query_params_and_validates_page(self) -> None:
        session = Mock()
        session.get.return_value = response(
            200,
            [{"unique_key": "1", "created_date": "2024-01-02"}],
        )
        client = SocrataClient(make_settings(), session=session)
        rows = client.fetch_page(0)
        self.assertEqual(len(rows), 1)
        params = session.get.call_args.kwargs["params"]
        self.assertIn("complaint_type = 'HEAT/HOT WATER'", params["$where"])
        self.assertEqual(params["$offset"], 0)

    def test_post_sends_form_data(self) -> None:
        session = Mock()
        session.post.return_value = response(
            200,
            [{"unique_key": "2", "created_date": "2024-02-03"}],
        )
        client = SocrataClient(make_settings("POST"), session=session)
        client.fetch_page(5)
        self.assertEqual(session.post.call_args.kwargs["data"]["$offset"], 5)
        session.get.assert_not_called()

    def test_retries_server_error_then_succeeds(self) -> None:
        session = Mock()
        session.get.side_effect = [
            response(503, [], "unavailable"),
            response(200, [{"unique_key": "1", "created_date": "2024-01-02"}]),
        ]
        client = SocrataClient(make_settings(), session=session)
        self.assertEqual(len(client.fetch_page(0)), 1)
        self.assertEqual(client.request_count, 2)

    def test_does_not_retry_client_error(self) -> None:
        session = Mock()
        session.get.return_value = response(400, [], "bad query")
        with self.assertRaises(NetworkError):
            SocrataClient(make_settings(), session=session).fetch_page(0)
        self.assertEqual(session.get.call_count, 1)

    def test_rejects_non_array_response(self) -> None:
        session = Mock()
        session.get.return_value = response(200, {"error": "bad shape"})
        with self.assertRaises(DataValidationError):
            SocrataClient(make_settings(), session=session).fetch_page(0)

    def test_rejects_record_missing_required_key(self) -> None:
        session = Mock()
        session.get.return_value = response(200, [{"created_date": "2024-01-02"}])
        with self.assertRaises(DataValidationError):
            SocrataClient(make_settings(), session=session).fetch_page(0)

    def test_rejects_invalid_json(self) -> None:
        session = Mock()
        result = response(200, None)
        result.json.side_effect = ValueError("invalid json")
        session.get.return_value = result
        with self.assertRaises(DataValidationError):
            SocrataClient(make_settings(), session=session).fetch_page(0)

    def test_count_endpoint_returns_integer(self) -> None:
        session = Mock()
        session.get.return_value = response(200, [{"record_count": "427458"}])
        client = SocrataClient(make_settings(), session=session)
        self.assertEqual(client.count_matching_records(), 427458)
        params = session.get.call_args.kwargs["params"]
        self.assertNotIn("$order", params)
        self.assertNotIn("$limit", params)

    def test_count_endpoint_rejects_bad_count(self) -> None:
        session = Mock()
        session.get.return_value = response(200, [{"record_count": "many"}])
        with self.assertRaises(DataValidationError):
            SocrataClient(make_settings(), session=session).count_matching_records()

    def test_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            SocrataClient(make_settings()).fetch_page(-1)


if __name__ == "__main__":
    unittest.main()
