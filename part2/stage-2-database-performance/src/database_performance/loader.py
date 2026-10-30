"""Validate Olist CSV rows and load them in one rollback-safe transaction."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, insert, text

from .schema import DATASETS, Dataset

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "sql" / "migrations"


class DatasetError(ValueError):
    """An Olist file does not match its declared schema."""


def apply_migrations(engine: Engine, *, include_indexes: bool = False) -> list[str]:
    """Apply unapplied migrations; candidate indexes require explicit opt-in."""
    applied: list[str] = []
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        known = set(connection.execute(text("SELECT version FROM public.schema_migrations")).scalars())
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name.startswith("004_"):
                continue
            if path.name.startswith("003_") and not include_indexes:
                continue
            if path.name in known:
                continue
            connection.exec_driver_sql(path.read_text(encoding="utf-8"))
            connection.execute(
                text("INSERT INTO public.schema_migrations (version) VALUES (:version)"),
                {"version": path.name},
            )
            applied.append(path.name)
    return applied


def retire_unused_geolocation_index(engine: Engine) -> list[str]:
    """Apply the optional retirement after plans show no dashboard uses geolocation."""
    migration = "004_drop_unused_geolocation_index.sql"
    path = MIGRATIONS_DIR / migration
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        if connection.execute(
            text("SELECT 1 FROM public.schema_migrations WHERE version = :version"),
            {"version": migration},
        ).first():
            return []
        connection.exec_driver_sql(path.read_text(encoding="utf-8"))
        connection.execute(
            text("INSERT INTO public.schema_migrations (version) VALUES (:version)"),
            {"version": migration},
        )
    return [migration]


def load_olist(engine: Engine, raw_dir: str | Path, *, batch_size: int = 2000) -> dict[str, Any]:
    """Replace all Olist tables from nine CSVs atomically; quarantine invalid rows.

    CSVs are streamed in bounded insert batches. Primary-key duplicates, field
    violations, and unresolved references are quarantined with their source row.
    Any unexpected database error rolls back the complete replacement.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    root = Path(raw_dir)
    missing = [dataset.filename for dataset in DATASETS if not (root / dataset.filename).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing Olist CSV files in {root}: {', '.join(missing)}")

    indexes: dict[str, set[tuple[Any, ...]]] = {}
    counts: dict[str, dict[str, int]] = {}
    quarantine: Counter[str] = Counter()
    quarantine_path = root.parent / "curated" / "integrity_quarantine.jsonl"
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".olist-quarantine-", suffix=".tmp", dir=quarantine_path.parent)
    temporary = Path(temp_name)
    committed = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as rejected:
            with engine.begin() as connection:
                connection.execute(text(
                    "TRUNCATE TABLE " + ", ".join(f'olist."{dataset.name}"' for dataset in reversed(DATASETS))
                    + " RESTART IDENTITY CASCADE"
                ))
                for dataset in DATASETS:
                    counts[dataset.name] = _load_dataset(
                        connection, root / dataset.filename, dataset, indexes,
                        rejected, quarantine, batch_size,
                    )
                for dataset in DATASETS:
                    connection.exec_driver_sql(f'ANALYZE olist."{dataset.name}"')
            committed = True
        try:
            os.replace(temporary, quarantine_path)
        except PermissionError as exc:
            raise OSError(
                "Database load committed, but Windows blocked publishing the quarantine file; "
                f"the temporary file was preserved at {temporary}"
            ) from exc
    finally:
        if not committed:
            temporary.unlink(missing_ok=True)
    return {
        "datasets": counts,
        "quarantined_by_reason": dict(sorted(quarantine.items())),
        "quarantine_file": str(quarantine_path),
        "loaded_rows": sum(item["loaded"] for item in counts.values()),
        "source_rows": sum(item["source"] for item in counts.values()),
    }


def _load_dataset(
    connection: Any,
    csv_path: Path,
    dataset: Dataset,
    indexes: dict[str, set[tuple[Any, ...]]],
    rejected: Any,
    quarantine: Counter[str],
    batch_size: int,
) -> dict[str, int]:
    expected = {field.source_name for field in dataset.fields}
    seen: set[tuple[Any, ...]] = set()
    pending: list[dict[str, Any]] = []
    source_count = loaded_count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        actual = set(reader.fieldnames or ())
        if actual != expected:
            raise DatasetError(
                f"{csv_path.name}: expected headers {sorted(expected)}, got {sorted(actual)}"
            )
        for line_number, raw in enumerate(reader, start=2):
            source_count += 1
            try:
                record = {field.name: field.parse(raw[field.source_name]) for field in dataset.fields}
                key = tuple(record[name] for name in dataset.key)
                if dataset.key and key in seen:
                    raise _Rejected("duplicate_primary_key")
                for field_name, parent_name in dataset.references:
                    value = record[field_name]
                    if value is None:
                        continue
                    parent_key = (value,)
                    parent_keys = indexes.get(parent_name)
                    if parent_keys is None or parent_key not in parent_keys:
                        raise _Rejected("unresolved_foreign_key")
            except _Rejected as exc:
                _write_rejection(rejected, quarantine, exc.reason, csv_path.name, line_number, raw)
                continue
            except (ValueError, TypeError) as exc:
                _write_rejection(rejected, quarantine, "invalid_value", csv_path.name, line_number,
                                 {"record": raw, "detail": str(exc)})
                continue
            pending.append(record)
            if dataset.key:
                seen.add(key)
            if len(pending) >= batch_size:
                connection.execute(insert(dataset.sql_table), pending)
                loaded_count += len(pending)
                pending.clear()
        if pending:
            connection.execute(insert(dataset.sql_table), pending)
            loaded_count += len(pending)
    if dataset.key:
        indexes[dataset.name] = seen
    return {"source": source_count, "loaded": loaded_count, "quarantined": source_count - loaded_count}


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _write_rejection(
    stream: Any, counts: Counter[str], reason: str, filename: str, row_number: int, record: Any,
) -> None:
    counts[reason] += 1
    stream.write(json.dumps({"reason": reason, "file": filename, "line": row_number, "record": record},
                            ensure_ascii=False, sort_keys=True) + "\n")
