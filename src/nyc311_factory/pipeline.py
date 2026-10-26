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
                raise CheckpointError(
                    "Offline replay requires a complete raw download checkpoint"
                )
            self._enforce_target(checkpoint["raw_count"])
            return checkpoint

        # Check the source's column types before downloading, if the schema check is configured.
        self.source_schema = self.client.validate_source_schema()
        # A finished download is reused as-is, so rerunning does not fetch pages again.
        if checkpoint and checkpoint["complete"]:
            self._enforce_target(checkpoint["raw_count"])
            return checkpoint

        # Resume from the saved offset; a fresh run starts at 0.
        offset = checkpoint["next_offset"] if checkpoint else 0
        raw_count = checkpoint["raw_count"] if checkpoint else 0
        while True:
            rows = self.client.fetch_page(offset)
            # An empty page means there are no more rows to download.
            if not rows:
                break
            # Write the page first, then the checkpoint, so a crash never points
            # to a page that was not saved.
            self._write_page(offset, rows)
            raw_count += len(rows)
            offset += len(rows)
            checkpoint = {
                "signature": self.settings.source_signature,
                "next_offset": offset,
                "raw_count": raw_count,
                # A short page means the API has no more rows.
                "complete": len(rows) < self.settings.page_size,
            }
            self._write_checkpoint(checkpoint)
            if checkpoint["complete"]:
                break

        # No checkpoint and no rows: record an empty but complete download.
        if checkpoint is None:
            checkpoint = {
                "signature": self.settings.source_signature,
                "next_offset": 0,
                "raw_count": 0,
                "complete": True,
            }
            self._write_checkpoint(checkpoint)
        # The loop ended because the API had no more rows, so mark the download complete.
        elif not checkpoint["complete"]:
            checkpoint["complete"] = True
            self._write_checkpoint(checkpoint)

        self._enforce_target(raw_count)
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
        if checkpoint.get("signature") != self.settings.source_signature:
            raise CheckpointError(
                "Checkpoint settings differ from this run; archive the raw directory "
                "before starting a different source slice"
            )
        try:
            next_offset = int(checkpoint["next_offset"])
            raw_count = int(checkpoint["raw_count"])
            complete = bool(checkpoint["complete"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointError(f"Checkpoint fields are invalid: {exc}") from exc
        if next_offset < 0 or raw_count != next_offset:
            raise CheckpointError("Checkpoint offsets and raw row count are inconsistent")
        # Every page the checkpoint claims to have written must exist on disk.
        if next_offset:
            page_size = self.settings.page_size
            full_pages = next_offset // page_size
            for page_number in range(full_pages):
                page_offset = page_number * page_size
                if not self._page_path(page_offset).is_file():
                    raise CheckpointError(f"Checkpoint page is missing: {page_offset}")
            # The last, partly filled page is named by its starting offset.
            remainder = next_offset % page_size
            if remainder and not self._page_path(next_offset - remainder).is_file():
                raise CheckpointError(f"Checkpoint page is missing: {next_offset - remainder}")
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
