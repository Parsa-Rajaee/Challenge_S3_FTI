"""Command-line setup, loading, and benchmarking CLI for the Stage 2 Olist database.

Commands:
  - init-db: Create base schemas (`olist`, `analytics`) and apply initial migrations.
  - load: Ingest 9 Olist CSV datasets transactionally with quarantine logging.
  - build: Execute the end-to-end setup (migrations + candidate indexes + data + snapshot rebuild).
  - add-indexes: Apply candidate performance indexes.
  - benchmark: Execute the 5 dashboard queries and measure catalog table/index storage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date


def _add_load_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raw-dir", default="data/raw", help="Path to raw CSV directory")
    parser.add_argument("--batch-size", type=int, default=2000, help="Insert batch row chunk size")
    parser.add_argument(
        "--stage1-csv",
        default="data/curated/curated_records.csv",
        help="Stage 1 output to load into the separate nyc311 schema",
    )
    parser.add_argument(
        "--skip-stage1",
        action="store_true",
        help="load Olist only, even if the Stage 1 curated CSV exists",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and inspect the Stage 2 Olist database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-db", help="create base Olist tables and analytics SQL")
    init.add_argument(
        "--reset",
        action="store_true",
        help="drop and recreate only the olist and analytics schemas",
    )

    load = subparsers.add_parser(
        "load", help="transactionally replace tables from nine Olist CSV files"
    )
    _add_load_arguments(load)

    build = subparsers.add_parser(
        "build",
        help="apply migrations and indexes, load Olist and Stage 1, rebuild snapshots",
    )
    _add_load_arguments(build)

    indexes = subparsers.add_parser("add-indexes", help="apply candidate dashboard indexes")
    indexes.add_argument(
        "--include-candidates",
        action="store_true",
        required=True,
        help="acknowledge indexes have write and storage costs",
    )

    benchmark = subparsers.add_parser("benchmark", help="measure each query and capture its plan")
    benchmark.add_argument(
        "--start-date",
        type=date.fromisoformat,
        required=True,
        help="Start date YYYY-MM-DD",
    )
    benchmark.add_argument(
        "--end-date",
        type=date.fromisoformat,
        required=True,
        help="End date YYYY-MM-DD",
    )
    benchmark.add_argument(
        "--repetitions",
        type=int,
        default=5,
        help="Number of query execution timing repetitions",
    )

    return parser


def _load_datasets(engine, args, url):
    from .loader import apply_migrations, load_olist, rebuild_monthly_snapshots

    stage1_path = os.path.abspath(args.stage1_csv)
    if not args.skip_stage1 and not os.path.isfile(stage1_path):
        raise FileNotFoundError(
            "Stage 1 curated CSV is required; supply --stage1-csv, "
            "run Stage 1 first, or explicitly use --skip-stage1"
        )
    include_indexes = args.command == "build"
    apply_migrations(
        engine,
        include_indexes=include_indexes,
        include_retirements=include_indexes,
    )
    result = load_olist(engine, args.raw_dir, batch_size=args.batch_size)
    result["applied_indexes"] = include_indexes

    # Load Stage 1 destination if available and not explicitly skipped
    if args.skip_stage1:
        result["stage1_destination"] = {"status": "skipped by request"}
    elif os.path.isfile(stage1_path):
        from nyc311_factory.database import load_curated_to_database

        result["stage1_destination"] = load_curated_to_database(stage1_path, database_url=url)
    else:
        raise FileNotFoundError(
            "Stage 1 curated CSV is required; supply --stage1-csv, "
            "run Stage 1 first, or explicitly use --skip-stage1"
        )

    # Rebuild snapshot table when building fully
    if args.command == "build":
        rebuild_monthly_snapshots(engine)
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in (
                "VACUUM (ANALYZE) olist.orders",
                "VACUUM (ANALYZE) olist.order_items",
                "VACUUM (ANALYZE) olist.order_payments",
                "VACUUM (ANALYZE) olist.order_reviews",
            ):
                connection.exec_driver_sql(statement)
        result["monthly_snapshot"] = "rebuilt"

    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error(
            "Set DATABASE_URL to a PostgreSQL SQLAlchemy URL (e.g. postgresql://user:pass@host:5432/db)"
        )

    try:
        from sqlalchemy import create_engine, text

        from .benchmark import benchmark_queries, database_sizes
        from .loader import apply_migrations

        engine = create_engine(url, pool_pre_ping=True)
        try:
            if args.command == "init-db":
                if args.reset:
                    with engine.begin() as connection:
                        connection.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
                        connection.execute(text("DROP SCHEMA IF EXISTS olist CASCADE"))
                        connection.execute(text("DROP TABLE IF EXISTS public.schema_migrations"))
                print(json.dumps({"applied_migrations": apply_migrations(engine)}, indent=2))

            elif args.command in {"load", "build"}:
                result = _load_datasets(engine, args, url)
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

            elif args.command == "add-indexes":
                print(
                    json.dumps(
                        {"applied_migrations": apply_migrations(engine, include_indexes=True)},
                        indent=2,
                    )
                )

            elif args.command == "benchmark":
                if args.start_date >= args.end_date:
                    parser.error("--start-date must be earlier than --end-date")
                print(
                    json.dumps(
                        {
                            "measurements": benchmark_queries(
                                engine,
                                args.start_date,
                                args.end_date,
                                repetitions=args.repetitions,
                            ),
                            "storage": database_sizes(engine),
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                )
        finally:
            engine.dispose()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
