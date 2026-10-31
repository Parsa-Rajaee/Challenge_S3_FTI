"""Repeatable live-query plans, timings, and index/storage measurements."""

from __future__ import annotations

import statistics
import time
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ClauseElement, Executable

QUERY_DIR = Path(__file__).resolve().parents[2] / "sql" / "queries"


class Explain(Executable, ClauseElement):
    """Compile EXPLAIN around a bound statement instead of concatenating SQL text."""

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
) -> dict[str, Any]:
    """Return full EXPLAIN ANALYZE plans and client timings for all five queries."""
    if repetitions < 3:
        raise ValueError("Use at least three repetitions for timing summaries")
    parameters = {"start_date": start_date, "end_date": end_date}
    results: dict[str, Any] = {}
    for path in sorted(QUERY_DIR.glob("*.sql")):
        statement = text(path.read_text(encoding="utf-8"))
        with engine.connect() as connection:
            plan = connection.execute(
                Explain(statement, analyze=True, buffers=True, format="JSON"),
                parameters,
            ).scalar_one()
            connection.execute(statement, parameters).all()  # warm cache and consume results
            samples_ms: list[float] = []
            for _ in range(repetitions):
                started = time.perf_counter()
                connection.execute(statement, parameters).all()
                samples_ms.append((time.perf_counter() - started) * 1000)
        results[path.stem] = {
            "client_elapsed_ms": [round(value, 3) for value in samples_ms],
            "client_median_ms": round(statistics.median(samples_ms), 3),
            "server_plan": plan[0]["Plan"],
            "server_execution_ms": plan[0]["Execution Time"],
            "server_planning_ms": plan[0]["Planning Time"],
        }
    return results


def database_sizes(engine: Engine) -> dict[str, Any]:
    """Measure Olist table and index bytes from PostgreSQL catalog statistics."""
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT c.relname AS table_name,
                   pg_table_size(c.oid) AS table_bytes,
                   pg_indexes_size(c.oid) AS index_bytes,
                   pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'olist' AND c.relkind = 'r'
            ORDER BY c.relname
        """)).mappings().all()
        index_rows = connection.execute(text("""
            SELECT table_class.relname AS table_name,
                   index_class.relname AS index_name,
                   pg_relation_size(index_class.oid) AS index_bytes
            FROM pg_index AS indexes
            JOIN pg_class AS table_class ON table_class.oid = indexes.indrelid
            JOIN pg_namespace AS n ON n.oid = table_class.relnamespace
            JOIN pg_class AS index_class ON index_class.oid = indexes.indexrelid
            WHERE n.nspname = 'olist'
            ORDER BY table_class.relname, index_class.relname
        """)).mappings().all()
    values = [dict(row) for row in rows]
    indexes = [dict(row) for row in index_rows]
    totals = {field: sum(int(row[field]) for row in values)
              for field in ("table_bytes", "index_bytes", "total_bytes")}
    return {
        "tables": values,
        "indexes": indexes,
        "totals": totals,
        "index_to_table_ratio": totals["index_bytes"] / totals["table_bytes"] if totals["table_bytes"] else 0,
    }
