"""Schema validation, quarantine, and deterministic curation of raw pages."""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .exceptions import DataValidationError

# Column order of curated_records.csv.
CURATED_FIELDS: tuple[str, ...] = (
    "unique_key",
    "created_date",
    "closed_date",
    "agency",
    "complaint_type",
    "descriptor",
    "incident_zip",
    "borough",
    "closure_days",
)

# The five NYC boroughs, in the upper-case form used throughout the project.
BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"}
# A 5-digit ZIP, optionally followed by -NNNN (ZIP+4). The 5 digits are captured as group 1.
ZIP_PATTERN = re.compile(r"^(\d{5})(?:-\d{4})?$")


def curate_raw_pages(
    settings: Settings,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Validate raw pages one at a time and atomically write curated outputs.

    Duplicate ``unique_key`` values retain their first valid occurrence, matching
    the source's stable ``created_date, unique_key`` ordering. Invalid rows are
    written to quarantine rather than silently discarded.
    """
    # Page file names are zero-padded (page_000000000.json), so sorting them keeps them in order.
    raw_pages = sorted(settings.raw_dir.glob("page_*.json"))
    if not raw_pages:
        raise DataValidationError(f"No raw pages found in {settings.raw_dir}")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    curated_path = destination / "curated_records.csv"
    quarantine_path = destination / "quarantine.jsonl"
    quality_path = destination / "quality_report.json"
    temporary_paths: list[Path] = []

    try:
        # Write everything to temporary files first. The real outputs are replaced only at the end.
        curated_tmp = _temporary_path(curated_path)
        quarantine_tmp = _temporary_path(quarantine_path)
        quality_tmp = _temporary_path(quality_path)
        temporary_paths.extend((curated_tmp, quarantine_tmp, quality_tmp))

        # Raw rows are streamed; exact distinct counts retain only unique field values.
        reason_counts: dict[str, int] = {}
        seen_keys: set[str] = set()
        distinct_values = {field: set() for field in CURATED_FIELDS if field != "unique_key"}
        null_counts = {field: 0 for field in CURATED_FIELDS}
        column_min: dict[str, Any] = {}
        column_max: dict[str, Any] = {}
        source_count = 0
        accepted_count = 0
        quarantined_count = 0

        # Open the curated CSV and the quarantine file together, and write rows as they are checked.
        with (
            curated_tmp.open("w", encoding="utf-8", newline="") as curated_file,
            quarantine_tmp.open("w", encoding="utf-8", newline="\n") as quarantine_file,
        ):
            curated_writer = csv.DictWriter(
                curated_file,
                fieldnames=CURATED_FIELDS,
                extrasaction="raise",
                lineterminator="\n",
            )
            curated_writer.writeheader()

            # Keep memory bounded to one raw page instead of loading the full export.
            for page_path in raw_pages:
                try:
                    page = json.loads(page_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise DataValidationError(
                        f"Cannot read raw page {page_path}: {exc}"
                    ) from exc
                if not isinstance(page, list):
                    raise DataValidationError(f"Raw page {page_path} must contain a JSON array")
                if len(page) > settings.page_size:
                    raise DataValidationError(
                        f"Raw page {page_path} contains {len(page)} rows; "
                        f"configured page size is {settings.page_size}"
                    )

                # Each record is either accepted (row is set) or rejected (reason is set).
                for raw_record in page:
                    source_count += 1
                    row, reason = _validate_record(raw_record, settings)
                    if reason is None:
                        if row is None:
                            raise DataValidationError(
                                "Record validation returned neither a row nor a reason"
                            )
                        # Page order follows the source's created_date/key ordering;
                        # preserve its first valid version and quarantine later copies.
                        if row["unique_key"] in seen_keys:
                            reason = "DUPLICATE_UNIQUE_KEY"
                        else:
                            seen_keys.add(row["unique_key"])

                    # Rejected rows keep their raw content so they can be inspected later.
                    if reason is not None:
                        quarantined_count += 1
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
                        quarantine_file.write(
                            json.dumps(
                                {"reason_code": reason, "record": raw_record},
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                    else:
                        if row is None:
                            raise DataValidationError(
                                "Record validation returned neither a row nor a reason"
                            )
                        curated_writer.writerow(row)
                        accepted_count += 1
                        for field, value in row.items():
                            if value is None or value == "":
                                null_counts[field] += 1
                                continue
                            if field != "unique_key":
                                distinct_values[field].add(value)
                            if field not in column_min or value < column_min[field]:
                                column_min[field] = value
                            if field not in column_max or value > column_max[field]:
                                column_max[field] = value

        # Share of the raw rows that were rejected. Guarded against dividing by zero.
        quarantine_ratio = quarantined_count / source_count if source_count else 0.0
        column_quality = {
            field: {
                "null_count": null_counts[field],
                "null_percentage": (
                    round(null_counts[field] / accepted_count * 100, 6)
                    if accepted_count
                    else None
                ),
                "distinct_count": (
                    accepted_count
                    if field == "unique_key"
                    else len(distinct_values[field])
                ),
                "min": column_min.get(field),
                "max": column_max.get(field),
            }
            for field in CURATED_FIELDS
        }
        summary = {
            "source_records": source_count,
            "accepted_records": accepted_count,
            "quarantined_records": quarantined_count,
            "quarantine_ratio": quarantine_ratio,
            "quarantine_by_reason": dict(sorted(reason_counts.items())),
            "column_quality": column_quality,
        }
        # Checked before the rename step, so a failed run never replaces good outputs.
        if quarantine_ratio > settings.max_quarantine_ratio:
            raise DataValidationError(
                f"Quarantine ratio {quarantine_ratio:.6f} exceeds configured maximum "
                f"{settings.max_quarantine_ratio:.6f}"
            )

        quality_tmp.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(curated_tmp, curated_path)
        os.replace(quarantine_tmp, quarantine_path)
        os.replace(quality_tmp, quality_path)
        # The temp files were moved into place, so the cleanup step has nothing left to delete.
        temporary_paths.clear()
        return summary
    finally:
        # If the run failed, delete any temporary files it left behind.
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)


def _validate_record(
    raw_record: Any,
    settings: Settings,
) -> tuple[dict[str, Any] | None, str | None]:
    # Each check returns (row, None) when the record is valid, or (None, reason_code) when it is not.
    # The checks run in order, and the first failure decides the reason.
    if not isinstance(raw_record, dict):
        return None, "RECORD_NOT_OBJECT"

    raw_key = raw_record.get("unique_key")
    if not isinstance(raw_key, (str, int)) or isinstance(raw_key, bool):
        return None, "MISSING_UNIQUE_KEY"
    unique_key = str(raw_key).strip()
    if not unique_key:
        return None, "MISSING_UNIQUE_KEY"

    created_value = raw_record.get("created_date")
    if not isinstance(created_value, str) or not created_value.strip():
        return None, "MISSING_CREATED_DATE"
    try:
        created = _parse_timestamp(created_value)
    except ValueError:
        return None, "INVALID_CREATED_DATE"
    if not settings.start_date <= created.date() < settings.end_date:
        return None, "CREATED_DATE_OUT_OF_RANGE"

    # closed_date is optional. If it is present, it must be a valid time not earlier than created_date.
    closed_value = raw_record.get("closed_date")
    closed: datetime | None = None
    if closed_value is not None and str(closed_value).strip():
        if not isinstance(closed_value, str):
            return None, "INVALID_CLOSED_DATE"
        try:
            closed = _parse_timestamp(closed_value)
        except ValueError:
            return None, "INVALID_CLOSED_DATE"
        if closed < created:
            return None, "CLOSED_BEFORE_CREATED"

    complaint = _normalize_text(raw_record.get("complaint_type"))
    if complaint is None:
        return None, "MISSING_COMPLAINT_TYPE"
    if complaint.upper() != settings.complaint_type.upper():
        return None, "UNEXPECTED_COMPLAINT_TYPE"

    borough_value = _normalize_text(raw_record.get("borough"))
    # "UNSPECIFIED" means the source has no borough, so it is stored as blank.
    borough: str | None = None
    if borough_value and borough_value.upper() != "UNSPECIFIED":
        borough = " ".join(borough_value.upper().split())
        if borough not in BOROUGHS:
            return None, "INVALID_BOROUGH"

    # How long the request stayed open, in fractional days.
    closure_days = None
    if closed is not None:
        closure_days = (closed - created).total_seconds() / 86_400

    # Build the cleaned row. The keys must match CURATED_FIELDS.
    return {
        "unique_key": unique_key,
        "created_date": _format_timestamp(created),
        "closed_date": _format_timestamp(closed) if closed else None,
        "agency": _normalize_text(raw_record.get("agency")),
        "complaint_type": settings.complaint_type,
        "descriptor": _normalize_text(raw_record.get("descriptor")),
        "incident_zip": _normalize_zip(raw_record.get("incident_zip")),
        "borough": borough,
        "closure_days": closure_days,
    }, None


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    # fromisoformat does not accept a trailing "Z" (UTC), so replace it with "+00:00".
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        # Socrata timestamps without an explicit offset are treated as UTC.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    # One consistent output format: UTC, microsecond precision, ending in "Z".
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _normalize_text(value: Any) -> str | None:
    # Trim spaces. Blank text becomes None, which means "missing".
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_zip(value: Any) -> str | None:
    text = _normalize_text(value)
    # Placeholder values such as "N/A" mean there is no ZIP code.
    if text is None or text.upper() in {"N/A", "NA", "00000"}:
        return None
    # Reduce ZIP+4 values to the 5-digit key used by the population join;
    # unusable values stay in the record as missing instead of rejecting it.
    match = ZIP_PATTERN.fullmatch(text)
    if match is None or match.group(1) == "00000":
        return None
    return match.group(1)


def _temporary_path(destination: Path) -> Path:
    # Create a unique empty file in the same folder. Staying on the same disk keeps os.replace() a fast, atomic rename.
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(name)
