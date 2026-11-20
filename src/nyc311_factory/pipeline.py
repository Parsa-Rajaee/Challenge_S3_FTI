"""Atomic, restartable raw-page ingestion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .api import SocrataClient
from .config import Settings
from .exceptions import CheckpointError, DataValidationError


class RawDownloader:
    """Save one response page at a time and resume from the last commit."""

    def __init__(self, settings: Settings, client: SocrataClient | None = None) -> None:
        self.settings = settings
        self.client = client or SocrataClient(settings)
        self.source_schema: dict[str, str] | None = None

    def run(self, *, offline: bool = False) -> dict[str, Any]:
        self.settings.raw_dir.mkdir(parents=True, exist_ok=True)
        # Load progress from an earlier run. None means this is a fresh start.
        checkpoint = self._load_checkpoint()
        if offline:
            # Offline replay must have a complete checkpoint; it never fetches data or schema.
            if checkpoint is None or not checkpoint["complete"]:
                raise CheckpointError("Offline replay requires a complete raw download checkpoint")
            self._enforce_target(checkpoint["raw_count"])
            return checkpoint

        # Check the source's column types before downloading, if the schema check is configured.
        self.source_schema = self.client.validate_source_schema()
        # A finished download is reused as-is, so rerunning does not fetch pages again.
        if checkpoint and checkpoint["complete"]:
            self._enforce_target(checkpoint["raw_count"])
            return checkpoint

        if checkpoint is None:
            checkpoint = {
                "signature": self.settings.source_signature,
                "next_offset": 0,
                "raw_count": 0,
                "complete": False,
            }

        while not checkpoint["complete"]:
            offset = checkpoint["next_offset"]
            rows = self.client.fetch_page(offset)
            if rows:
                # Commit the page before advancing the checkpoint so a retry is safe.
                self._write_page(offset, rows)
                checkpoint["next_offset"] += len(rows)
                checkpoint["raw_count"] += len(rows)
            checkpoint["complete"] = not rows or len(rows) < self.settings.page_size
            self._write_checkpoint(checkpoint)

        self._enforce_target(checkpoint["raw_count"])
        return checkpoint

    def _enforce_target(self, raw_count: int) -> None:
        # Fails if too few rows came back, which often means a broken or empty export.
        if raw_count < self.settings.target_min_records:
            raise DataValidationError(
                f"Downloaded {raw_count} rows; minimum configured target is "
                f"{self.settings.target_min_records}"
            )

    def _load_checkpoint(self) -> dict[str, Any] | None:
        path = self.settings.checkpoint_path
        if not path.exists():
            return None
        try:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"Cannot read checkpoint {path}: {exc}") from exc
        # Refuse to resume if the saved checkpoint was made with different settings.
        if not isinstance(checkpoint, dict):
            raise CheckpointError("Checkpoint must be a JSON object")
        if checkpoint.get("signature") != self.settings.source_signature:
            raise CheckpointError(
                "Checkpoint settings differ from this run; archive the raw directory "
                "before starting a different source slice"
            )
        next_offset = checkpoint.get("next_offset")
        raw_count = checkpoint.get("raw_count")
        complete = checkpoint.get("complete")
        if type(next_offset) is not int or type(raw_count) is not int:
            raise CheckpointError("Checkpoint offsets and counts must be integers")
        if not isinstance(complete, bool):
            raise CheckpointError("Checkpoint completion flag must be true or false")
        if next_offset < 0 or raw_count != next_offset:
            raise CheckpointError("Checkpoint offsets and raw row count are inconsistent")
        # Every page the checkpoint claims to have written must exist on disk.
        for page_offset in range(0, next_offset, self.settings.page_size):
            if not self._page_path(page_offset).is_file():
                raise CheckpointError(f"Checkpoint page is missing: {page_offset}")
        return {
            "signature": checkpoint["signature"],
            "next_offset": next_offset,
            "raw_count": raw_count,
            "complete": complete,
        }

    def _page_path(self, offset: int) -> Path:
        # Pages are named by their starting row, e.g. page_000050000.json.
        return self.settings.raw_dir / f"page_{offset:09d}.json"

    def _write_page(self, offset: int, rows: list[dict[str, Any]]) -> None:
        destination = self._page_path(offset)
        # Write to a temp file, then rename: readers see either the old or the full new page.
        temporary = destination.with_suffix(".json.tmp")
        serialized = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary.write_text(serialized + "\n", encoding="utf-8")
        os.replace(temporary, destination)

    def _write_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        # Same temp-file-then-rename trick, so the checkpoint is never left half-written.
        path = self.settings.checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
