"""Reproducible Stage 2 experiments; all destructive setup is explicit and isolated."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, Float, Integer, String, text

from .benchmark import (
    QUERY_DIR,
    benchmark_queries,
    database_sizes,
    measure_insert_cost,
)
from .loader import apply_migrations, load_olist, rebuild_monthly_snapshots
from .schema import DATASETS

RETIRED_INDEXES = {
    "idx_geolocation_zip", "idx_orders_delivered_purchase", "idx_orders_customer",
    "idx_order_items_product", "idx_order_payments_order", "idx_products_category",
}


def prepare_database(engine: Engine, raw_dir: Path, stage1_csv: Path) -> dict[str, Any]:
    """Replace only Stage 2 schemas, then load both stages through their packages.

    Use a disposable database: existing olist/analytics objects are intentionally
    removed so a second fresh-kernel run cannot inherit experimental indexes.
    """
    missing = [dataset.filename for dataset in DATASETS if not (raw_dir / dataset.filename).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing Olist inputs: {', '.join(missing)}")
    if not stage1_csv.is_file():
        raise FileNotFoundError("Stage 1 curated_records.csv is required; run Stage 1 first")
    from nyc311_factory.database import load_curated_to_database

    started = time.perf_counter()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
        connection.execute(text("DROP SCHEMA IF EXISTS olist CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS public.schema_migrations"))
    migrations = apply_migrations(engine)
    olist = load_olist(engine, raw_dir)
    olist["quarantine_file"] = "data/curated/integrity_quarantine.jsonl"
    stage1 = load_curated_to_database(
        stage1_csv, database_url=engine.url.render_as_string(hide_password=False),
    )
    return {
        "base_migrations": migrations, "olist": olist, "stage1": stage1,
        "initial_load_seconds": round(time.perf_counter() - started, 3),
    }


def maintain_visibility(engine: Engine) -> None:
    """Make static imported data visible to index-only scans, outside transactions."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in (
            "VACUUM (ANALYZE) olist.orders",
            "VACUUM (ANALYZE) olist.order_items",
            "VACUUM (ANALYZE) olist.order_payments",
            "VACUUM (ANALYZE) olist.order_reviews",
        ):
            connection.exec_driver_sql(statement)


def plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(plan_nodes(child))
    return nodes


def verify_equal_queries(engine: Engine, first: Path, second: Path, parameters: dict) -> int:
    """Compare ordered exact SQLAlchemy rows, without constructing compound SQL."""
    with engine.connect() as connection:
        left = connection.execute(text(first.read_text(encoding="utf-8")), parameters).all()
        right = connection.execute(text(second.read_text(encoding="utf-8")), parameters).all()
    if left != right:
        raise AssertionError(f"Query results differ: {first.name} versus {second.name}")
    return len(left)


def collect_experiment(
    engine: Engine, start_date: date, end_date: date, *, repetitions: int = 5,
) -> dict[str, Any]:
    """Measure baseline, indexes, rewrite, retirement, and the selected snapshot path."""
    started = time.perf_counter()
    parameters = {"start_date": start_date, "end_date": end_date}
    baselines = QUERY_DIR.parent / "baselines"
    overrides = {
        "01_monthly_revenue": baselines / "01_monthly_revenue_view.sql",
        "05_payments": baselines / "05_payments.sql",
    }
    maintain_visibility(engine)
    baseline = benchmark_queries(engine, start_date, end_date, repetitions=repetitions, overrides=overrides)
    storage_before = database_sizes(engine)
    migrations = apply_migrations(engine, include_indexes=True)
    maintain_visibility(engine)
    indexed = benchmark_queries(engine, start_date, end_date, repetitions=repetitions, overrides=overrides)
    rewritten = benchmark_queries(
        engine, start_date, end_date, repetitions=repetitions,
        overrides={"01_monthly_revenue": overrides["01_monthly_revenue"]},
    )
    payment_equal_rows = verify_equal_queries(
        engine, overrides["05_payments"], QUERY_DIR / "05_payments.sql", parameters,
    )
    used = {
        node["Index Name"] for phase in (indexed, rewritten) for result in phase.values()
        for node in plan_nodes(result["server_plan"]) if node.get("Index Name")
    }
    if used & RETIRED_INDEXES:
        raise AssertionError(f"Do not retire indexes used by this workload: {sorted(used & RETIRED_INDEXES)}")
    storage_candidates = database_sizes(engine)
    retirement_migrations = apply_migrations(engine, include_indexes=True, include_retirements=True)
    refresh_started = time.perf_counter()
    rebuild_monthly_snapshots(engine)
    refresh_ms = round((time.perf_counter() - refresh_started) * 1000, 3)
    snapshot_equal_rows = verify_equal_queries(
        engine, overrides["01_monthly_revenue"], QUERY_DIR / "01_monthly_revenue.sql", parameters,
    )
    final = benchmark_queries(engine, start_date, end_date, repetitions=repetitions)
    storage_final = database_sizes(engine)
    write_cost = measure_insert_cost(engine)
    with engine.connect() as connection:
        environment = dict(connection.execute(text("""
            SELECT version() AS postgresql_version,
                   current_setting('work_mem') AS work_mem,
                   current_setting('shared_buffers') AS shared_buffers,
                   current_setting('max_parallel_workers_per_gather') AS parallel_workers_per_gather
        """)).mappings().one())
    comparison = {
        name: {
            "baseline_ms": baseline[name]["client_median_ms"],
            "indexed_ms": indexed[name]["client_median_ms"],
            "rewritten_live_ms": rewritten[name]["client_median_ms"],
            "final_ms": result["client_median_ms"],
            "final_max_ms": result["client_max_ms"],
            "median_under_200ms": result["client_median_ms"] < 200,
            "all_samples_under_200ms": result["client_max_ms"] < 200,
        }
        for name, result in final.items()
    }
    return {
        "cohort": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "repetitions": repetitions, "environment": environment,
        "baseline": baseline, "indexed_baseline": indexed, "rewritten_live": rewritten,
        "final": final, "query_comparison": comparison,
        "index_migrations": migrations, "retirement_migrations": retirement_migrations,
        "indexes_seen_before_retirement": sorted(used),
        "retired_indexes": sorted(RETIRED_INDEXES),
        "storage_before": storage_before, "storage_candidates": storage_candidates,
        "storage_final": storage_final, "write_cost": write_cost,
        "snapshot_refresh_ms": refresh_ms,
        "equivalence": {"payment_groups": payment_equal_rows, "monthly_category_rows": snapshot_equal_rows},
        "experiment_seconds": round(time.perf_counter() - started, 3),
    }


def bridge_demo(engine: Engine, start_date: date, end_date: date) -> dict[str, Any]:
    """Stream a view and write a real derived summary with explicit SQLAlchemy types."""
    statement = text("""
        SELECT customer_state, delay_days
        FROM analytics.order_delivery_reviews
        WHERE order_purchase_timestamp >= :start_date AND order_purchase_timestamp < :end_date
    """)
    totals: dict[str, dict[str, float]] = {}
    chunk_sizes = []
    with engine.connect().execution_options(stream_results=True) as connection:
        for chunk in pd.read_sql(
            statement, connection, params={"start_date": start_date, "end_date": end_date}, chunksize=20000,
        ):
            chunk_sizes.append(len(chunk))
            for state, group in chunk.groupby("customer_state"):
                summary = totals.setdefault(str(state), {"sum": 0.0, "count": 0})
                summary["sum"] += float(group["delay_days"].sum())
                summary["count"] += len(group)
    frame = pd.DataFrame([
        {"state": state, "avg_delay_days": total["sum"] / total["count"],
         "sample_orders": total["count"]}
        for state, total in sorted(totals.items())
    ])
    dtype_mapping: Any = {"state": String(2), "avg_delay_days": Float(), "sample_orders": Integer()}
    with engine.begin() as connection:
        frame.to_sql(
            "demo_state_summary", connection, schema="analytics", if_exists="replace", index=False,
            dtype=dtype_mapping,
        )
        delay = connection.execute(text("""
            SELECT analytics.delivery_delay_days(
                '2017-01-10 12:00:00'::timestamp, '2017-01-08 12:00:00'::timestamp
            )
        """)).scalar_one()
        month = date(2017, 1, 1)
        rows = text("SELECT * FROM analytics.monthly_category_snapshot WHERE month = :month ORDER BY category")
        connection.execute(text("CALL analytics.rebuild_monthly_snapshot(:month)"), {"month": month})
        first = connection.execute(rows, {"month": month}).all()
        connection.execute(text("CALL analytics.rebuild_monthly_snapshot(:month)"), {"month": month})
        second = connection.execute(rows, {"month": month}).all()
        if first != second:
            raise AssertionError("Monthly procedure is not idempotent")
    return {
        "chunk_sizes": chunk_sizes, "total_view_rows": sum(chunk_sizes),
        "state_summary_rows": len(frame), "function_delay_days": delay,
        "procedure_idempotent": first == second, "snapshot_month_rows": len(first),
    }


def show_query_evidence(experiment: dict, name: str) -> None:
    """Print traceable SQL, all repeated times, and complete before/after plans."""
    for label in ("baseline", "indexed_baseline", "rewritten_live", "final"):
        print(label)
        print(json.dumps(experiment[label][name], ensure_ascii=False, indent=2))


def save_experiment(experiment: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(experiment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
