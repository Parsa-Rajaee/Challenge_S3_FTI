"""Validate Olist CSV rows and load them in one rollback-safe database transaction.

Key Operational Features:
  - Atomic Load: All 9 datasets are loaded inside a single PostgreSQL transaction.
    If an unexpected database failure occurs, the entire load rolls back.
  - In-Memory Referential Pre-Validation: Foreign key references and composite
    primary keys are verified in Python memory sets before insertion, allowing
    violating rows to be safely quarantined without aborting the transaction.
  - Quarantine Audit Trail: Discarded rows are written line-by-line to a JSON Lines
    file (`integrity_quarantine.jsonl`) with the exact rejection reason and source line.
  - Statistics Collection: Runs `ANALYZE` immediately after data loading so the
    PostgreSQL query planner has accurate row estimates and histograms.
"""

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

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
MIGRATIONS_DIR = SQL_DIR / "migrations"
TRUNCATE_OLIST_SQL = (SQL_DIR / "load" / "truncate_olist.sql").read_text(encoding="utf-8")
ANALYZE_OLIST_SQL = (SQL_DIR / "load" / "analyze_olist.sql").read_text(encoding="utf-8")
REBUILD_SNAPSHOTS_SQL = (SQL_DIR / "load" / "rebuild_snapshots.sql").read_text(encoding="utf-8")


class DatasetError(ValueError):
    """Raised when an Olist CSV file does not match its declared schema or headers."""


def apply_migrations(
    engine: Engine, *, include_indexes: bool = False, include_retirements: bool = False,
) -> list[str]:
    """Apply pending SQL schema migrations tracked in public.schema_migrations.

    Args:
        engine: SQLAlchemy database engine.
        include_indexes: Apply candidate and covering-index migrations when True.
                         Otherwise omit them for a primary-key-only baseline.
        include_retirements: Apply the plan-justified final index retirements.

    Returns:
        List of newly applied migration file names.
    """
    if include_retirements and not include_indexes:
        raise ValueError("Retirements require the complete index migration sequence")
    applied: list[str] = []
    with engine.begin() as connection:
        # Create migration tracking table if it does not yet exist
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        known = set(connection.execute(text("SELECT version FROM public.schema_migrations")).scalars())

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            # Retire candidates only after plan evidence, or for the final build.
            if path.name[:3] in {"004", "006"} and not include_retirements:
                continue
            # Performance indexes are deliberately omitted from baseline builds.
            if path.name[:3] in {"003", "005"} and not include_indexes:
                continue
            if path.name in known:
                continue

            # Literal migration comments may contain percent signs (psycopg2).
            connection.exec_driver_sql(
                path.read_text(encoding="utf-8"), execution_options={"no_parameters": True}
            )
            connection.execute(
                text("INSERT INTO public.schema_migrations (version) VALUES (:version)"),
                {"version": path.name},
            )
            applied.append(path.name)
    return applied


def retire_unused_geolocation_index(engine: Engine) -> list[str]:
    """Execute migration 004 to drop the unused geolocation index.

    Invoked after query plans prove that none of the five analytical questions
    access `olist.geolocation`. The notebook measures the space reclaimed.
    """
    migration = "004_drop_unused_geolocation_index.sql"
    path = MIGRATIONS_DIR / migration
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        # Check if already applied
        if connection.execute(
            text("SELECT 1 FROM public.schema_migrations WHERE version = :version"),
            {"version": migration},
        ).first():
            return []

        connection.exec_driver_sql(
            path.read_text(encoding="utf-8"), execution_options={"no_parameters": True}
        )
        connection.execute(
            text("INSERT INTO public.schema_migrations (version) VALUES (:version)"),
            {"version": migration},
        )
    return [migration]


def load_olist(engine: Engine, raw_dir: str | Path, *, batch_size: int = 2000) -> dict[str, Any]:
    """Replace all Olist tables from nine CSV files atomically; quarantine invalid rows.

    Workflow:
      1. Verify all 9 CSV files exist in `raw_dir`.
      2. Prepare an atomic temporary quarantine file on disk.
      3. Begin a single database transaction (`with engine.begin()`):
         a. Truncate all tables in the `olist` schema (`CASCADE`).
         b. Ingest datasets in strict dependency order (Translations -> Customers -> ...).
         c. Stream records in bounded chunks (`batch_size`), inserting via SQLAlchemy bulk inserts.
         d. Catch schema violations and broken FKs, writing them to the quarantine file.
         e. Run `ANALYZE olist.*` to refresh PostgreSQL query planner statistics.
      4. Commit transaction and atomically rename the temporary quarantine file to
         `data/curated/integrity_quarantine.jsonl`.
      5. If an unhandled exception occurs, transaction rolls back completely and the
         temporary file is cleaned up.

    Returns:
      Summary dictionary with row counts, quarantine breakdown, and file paths.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    root = Path(raw_dir)
    missing = [dataset.filename for dataset in DATASETS if not (root / dataset.filename).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing Olist CSV files in {root}: {', '.join(missing)}")

    # In-memory index cache: dataset_name -> set of primary key tuples (for FK validation)
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
                # Truncate existing data cleanly
                connection.exec_driver_sql(TRUNCATE_OLIST_SQL)

                # Ingest datasets in declared dependency order
                for dataset in DATASETS:
                    counts[dataset.name] = _load_dataset(
                        connection,
                        root / dataset.filename,
                        dataset,
                        indexes,
                        rejected,
                        quarantine,
                        batch_size,
                    )

                # Refresh PostgreSQL cost statistics
                connection.exec_driver_sql(ANALYZE_OLIST_SQL)
            committed = True

        # Atomically publish quarantine file after successful database commit
        try:
            os.replace(temporary, quarantine_path)
        except PermissionError as exc:
            raise OSError(
                "Database load committed, but Windows blocked publishing the quarantine file; "
                f"the temporary file was preserved at {temporary}"
            ) from exc
    finally:
        # If transaction aborted, clean up temporary file
        if not committed:
            temporary.unlink(missing_ok=True)

    return {
        "datasets": counts,
        "quarantined_by_reason": dict(sorted(quarantine.items())),
        "quarantine_file": str(quarantine_path),
        "loaded_rows": sum(item["loaded"] for item in counts.values()),
        "source_rows": sum(item["source"] for item in counts.values()),
    }


def rebuild_monthly_snapshots(engine: Engine) -> None:
    """Rebuild all delivered-order months in analytics.monthly_category_snapshot."""
    with engine.begin() as connection:
        connection.exec_driver_sql(REBUILD_SNAPSHOTS_SQL)


def _load_dataset(
    connection: Any,
    csv_path: Path,
    dataset: Dataset,
    indexes: dict[str, set[tuple[Any, ...]]],
    rejected: Any,
    quarantine: Counter[str],
    batch_size: int,
) -> dict[str, int]:
    """Parse, validate, and stream insert a single CSV dataset into PostgreSQL."""
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
                # 1. Field validation and type parsing
                record = {field.name: field.parse(raw[field.source_name]) for field in dataset.fields}

                # 2. In-memory Primary Key uniqueness check
                key = tuple(record[name] for name in dataset.key)
                if dataset.key and key in seen:
                    raise _Rejected("duplicate_primary_key")

                # 3. In-memory Foreign Key reference checks
                for field_name, parent_name in dataset.references:
                    value = record[field_name]
                    if value is None:
                        continue
                    parent_key = (value,)
                    parent_keys = indexes.get(parent_name)
                    if parent_keys is None or parent_key not in parent_keys:
                        raise _Rejected("unresolved_foreign_key")

            except _Rejected as exc:
                # Record quarantined row due to integrity constraint
                _write_rejection(rejected, quarantine, exc.reason, csv_path.name, line_number, raw)
                continue
            except (ValueError, TypeError) as exc:
                # Record quarantined row due to datatype / range validation failure
                _write_rejection(
                    rejected,
                    quarantine,
                    "invalid_value",
                    csv_path.name,
                    line_number,
                    {"record": raw, "detail": str(exc)},
                )
                continue

            pending.append(record)
            if dataset.key:
                seen.add(key)

            # Flush batch insert to database when buffer reaches batch_size
            if len(pending) >= batch_size:
                connection.execute(insert(dataset.sql_table), pending)
                loaded_count += len(pending)
                pending.clear()

        # Flush any remaining rows in the final batch
        if pending:
            connection.execute(insert(dataset.sql_table), pending)
            loaded_count += len(pending)
            pending.clear()

    # Cache primary keys in memory for downstream dependent datasets
    if dataset.key:
        indexes[dataset.name] = seen

    return {
        "source": source_count,
        "loaded": loaded_count,
        "quarantined": source_count - loaded_count,
    }


class _Rejected(Exception):
    """Internal sentinel exception for rows routed to the quarantine log."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


def _write_rejection(
    stream: Any,
    counts: Counter[str],
    reason: str,
    filename: str,
    row_number: int,
    record: Any,
) -> None:
    """Format and write a quarantined record to the JSON Lines stream."""
    counts[reason] += 1
    stream.write(
        json.dumps(
            {
                "reason": reason,
                "file": filename,
                "line": row_number,
                "record": record,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
