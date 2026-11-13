"""Repeatable live-query plans, timings, and PostgreSQL index/storage measurements.

Key Operational Features:
  - SQLAlchemy Explain Compiler: Extends SQLAlchemy's AST to compile PostgreSQL
    `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` around parameterized statements
    without brittle string manipulation.
  - Multi-Sample Benchmarking: Runs each dashboard query across multiple iterations
    (default 5), recording server-side planning and execution times as well as
    client-side median wall clock timings.
  - Catalog Inspection: Queries `pg_class`, `pg_namespace`, and `pg_index` to
    measure table bytes, index bytes, and index-to-table storage ratios.
"""

from __future__ import annotations

import statistics
import time
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Engine, Index, MetaData, Table, insert, select, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ClauseElement, Executable

from .schema import DATASETS

QUERY_DIR = Path(__file__).resolve().parents[2] / "sql" / "queries"


class Explain(Executable, ClauseElement):
    """SQLAlchemy ClauseElement representing an EXPLAIN query wrapper.

    Allows parameterized statements to be explained using bound parameters,
    preserving query cache safety and avoiding raw string concatenation.
    """

    inherit_cache = False

    def __init__(
        self,
        statement: Any,
        *,
        analyze: bool = False,
        buffers: bool = False,
        format: str | None = None,
    ) -> None:
        self.statement = statement
        self.analyze = analyze
        self.buffers = buffers
        self.format = format


@compiles(Explain)
def _compile_explain(element: Explain, compiler: Any, **kwargs: Any) -> str:
    """Compile the Explain ClauseElement into a native PostgreSQL EXPLAIN statement."""
    options: list[str] = []
    if element.analyze:
        options.append("ANALYZE")
    if element.buffers:
        options.append("BUFFERS")
    if element.format:
        options.append(f"FORMAT {element.format}")
    prefix = "EXPLAIN"
    if options:
        prefix += " (" + ", ".join(options) + ")"
    return f"{prefix} {compiler.process(element.statement, **kwargs)}"


def benchmark_queries(
    engine: Engine,
    start_date: date,
    end_date: date,
    *,
    repetitions: int = 5,
    overrides: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Execute all five queries, capturing server execution plans and client latency.

    Args:
        engine: SQLAlchemy Engine connected to the target database.
        start_date: Beginning of the date window (e.g. 2017-09-01).
        end_date: End of the date window (e.g. 2018-09-01).
        repetitions: Number of timing runs (minimum 3) to compute median latency.

    Returns:
        Dictionary mapping query filename stems to server plans, execution times,
        planning times, and client elapsed timing samples.
    """
    if repetitions < 3:
        raise ValueError("Use at least three repetitions for timing summaries")
    parameters = {"start_date": start_date, "end_date": end_date}
    results: dict[str, Any] = {}

    if start_date >= end_date:
        raise ValueError("start_date must precede end_date")
    for path in sorted(QUERY_DIR.glob("*.sql")):
        selected = (overrides or {}).get(path.stem, path)
        results[path.stem] = benchmark_statement(
            engine, selected.read_text(encoding="utf-8"), parameters,
            repetitions=repetitions,
        )
    return results


def benchmark_statement(
    engine: Engine,
    sql: str,
    parameters: dict[str, Any],
    *,
    repetitions: int = 5,
) -> dict[str, Any]:
    """Warm once, fetch every row, then record repeated client times and a real plan."""
    if repetitions < 3:
        raise ValueError("Use at least three repetitions for timing summaries")
    statement = text(sql)
    samples_ms = []
    with engine.connect() as connection:
        connection.execute(text("SELECT set_config('statement_timeout', '15000', true)"))
        row_count = len(connection.execute(statement, parameters).all())
        for _ in range(repetitions):
            started = time.perf_counter()
            connection.execute(statement, parameters).all()
            samples_ms.append((time.perf_counter() - started) * 1000)
        plan = connection.execute(
            Explain(statement, analyze=True, buffers=True, format="JSON"), parameters,
        ).scalar_one()[0]
    return {
        "sql": sql,
        "row_count": row_count,
        "client_elapsed_ms": [round(value, 3) for value in samples_ms],
        "client_median_ms": round(statistics.median(samples_ms), 3),
        "client_max_ms": round(max(samples_ms), 3),
        "server_plan": plan["Plan"],
        "server_execution_ms": plan["Execution Time"],
        "server_planning_ms": plan["Planning Time"],
    }


def measure_insert_cost(engine: Engine, *, rows: int = 50000, repetitions: int = 3) -> dict[str, Any]:
    """Compare identical bulk inserts with/without Q5's payment covering index.

    Parsing, table/index creation and ANALYZE are outside the timed section.
    Each sample rolls back its temporary table; production tables are read only.
    """
    if rows < 1 or repetitions < 3:
        raise ValueError("Use positive rows and at least three repetitions")
    dataset = next(dataset for dataset in DATASETS if dataset.name == "order_payments")
    source = dataset.sql_table
    samples: dict[str, list[float]] = {"primary_key_only": [], "with_covering_index": []}
    inserted = 0
    for repetition in range(repetitions):
        phases = list(samples)
        if repetition % 2:
            phases.reverse()
        for phase in phases:
            metadata = MetaData()
            sample = Table(
                "stage2_write_sample", metadata,
                *(Column(field.name, field.sql_type, primary_key=field.name in dataset.key,
                         nullable=field.nullable) for field in dataset.fields),
                prefixes=["TEMPORARY"], postgresql_on_commit="DROP",
            )
            with engine.connect() as connection, connection.begin() as transaction:
                sample.create(connection)
                if phase == "with_covering_index":
                    Index(
                        "stage2_write_cover", sample.c.order_id, sample.c.payment_type,
                        sample.c.payment_installments, postgresql_include=["payment_value"],
                    ).create(connection)
                statement = insert(sample).from_select(
                    list(source.c.keys()), select(source).order_by(
                        source.c.order_id, source.c.payment_sequential,
                    ).limit(rows),
                )
                started = time.perf_counter()
                inserted = connection.execute(statement).rowcount
                samples[phase].append((time.perf_counter() - started) * 1000)
                transaction.rollback()
    medians = {name: round(statistics.median(values), 3) for name, values in samples.items()}
    return {
        "rows_per_sample": inserted,
        "repetitions": repetitions,
        "samples_ms": {name: [round(value, 3) for value in values] for name, values in samples.items()},
        "median_ms": medians,
        "covering_to_primary_ratio": round(medians["with_covering_index"] / medians["primary_key_only"], 3),
    }


def database_sizes(engine: Engine) -> dict[str, Any]:
    """Inspect PostgreSQL catalog metadata to compute table and index storage sizes.

    Queries:
      - `pg_table_size`: Data fork size of the heap table (excluding indexes).
      - `pg_indexes_size`: Total storage occupied by all indexes associated with the table.
      - `pg_total_relation_size`: Total footprint including table, indexes, and TOAST.

    Returns:
      Dictionary containing per-table sizes, per-index sizes, and totals in bytes.
    """
    with engine.connect() as connection:
        # Measure table-level storage
        rows = connection.execute(
            text(
                """
            SELECT c.relname AS table_name,
                   pg_table_size(c.oid) AS table_bytes,
                   pg_indexes_size(c.oid) AS index_bytes,
                   pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'olist' AND c.relkind = 'r'
            ORDER BY c.relname
        """
            )
        ).mappings().all()

        # Measure individual index storage
        index_rows = connection.execute(
            text(
                """
            SELECT table_class.relname AS table_name,
                   index_class.relname AS index_name,
                   pg_relation_size(index_class.oid) AS index_bytes
            FROM pg_index AS indexes
            JOIN pg_class AS table_class ON table_class.oid = indexes.indrelid
            JOIN pg_namespace AS n ON n.oid = table_class.relnamespace
            JOIN pg_class AS index_class ON index_class.oid = indexes.indexrelid
            WHERE n.nspname = 'olist'
            ORDER BY table_class.relname, index_class.relname
        """
            )
        ).mappings().all()

    values = [dict(row) for row in rows]
    indexes = [dict(row) for row in index_rows]
    totals = {
        field: sum(int(row[field]) for row in values)
        for field in ("table_bytes", "index_bytes", "total_bytes")
    }

    return {
        "tables": values,
        "indexes": indexes,
        "totals": totals,
        "index_to_table_ratio": (
            totals["index_bytes"] / totals["table_bytes"] if totals["table_bytes"] else 0
        ),
    }
