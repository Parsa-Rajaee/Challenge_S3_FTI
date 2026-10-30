"""Command-line setup and loading for the Stage 2 PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and inspect the Stage 2 Olist database")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init-db", help="create base Olist tables and analytics SQL")
    init.add_argument("--reset", action="store_true", help="drop/recreate only the olist and analytics schemas")
    load = subparsers.add_parser("load", help="transactionally replace tables from nine Olist CSV files")
    load.add_argument("--raw-dir", default="data/raw")
    load.add_argument("--batch-size", type=int, default=2000)
    load.add_argument("--stage1-csv", default="data/curated/curated_records.csv",
                      help="Stage 1 output to load into the separate nyc311 schema")
    load.add_argument("--skip-stage1", action="store_true",
                      help="load Olist only, even if the Stage 1 curated CSV exists")
    indexes = subparsers.add_parser("add-indexes", help="apply candidate dashboard indexes")
    indexes.add_argument("--include-candidates", action="store_true", required=True,
                         help="acknowledge indexes have write/storage costs")
    benchmark = subparsers.add_parser("benchmark", help="measure each query and capture its plan")
    benchmark.add_argument("--start-date", type=date.fromisoformat, required=True)
    benchmark.add_argument("--end-date", type=date.fromisoformat, required=True)
    benchmark.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("Set DATABASE_URL to a PostgreSQL SQLAlchemy URL")
    try:
        from sqlalchemy import create_engine, text

        from .benchmark import benchmark_queries, database_sizes
        from .loader import apply_migrations, load_olist

        engine = create_engine(url, pool_pre_ping=True)
        try:
            if args.command == "init-db":
                if args.reset:
                    with engine.begin() as connection:
                        connection.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
                        connection.execute(text("DROP SCHEMA IF EXISTS olist CASCADE"))
                        connection.execute(text("DROP TABLE IF EXISTS public.schema_migrations"))
                print(json.dumps({"applied_migrations": apply_migrations(engine)}, indent=2))
            elif args.command == "load":
                apply_migrations(engine)
                result = load_olist(engine, args.raw_dir, batch_size=args.batch_size)
                stage1_path = os.path.abspath(args.stage1_csv)
                if args.skip_stage1:
                    result["stage1_destination"] = {"status": "skipped by request"}
                elif os.path.isfile(stage1_path):
                    from nyc311_factory.database import load_curated_to_database

                    result["stage1_destination"] = load_curated_to_database(stage1_path, database_url=url)
                else:
                    result["stage1_destination"] = {
                        "status": "not loaded; Stage 1 curated CSV is missing",
                        "expected_path": stage1_path,
                    }
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            elif args.command == "add-indexes":
                print(json.dumps({"applied_migrations": apply_migrations(engine, include_indexes=True)}, indent=2))
            else:
                if args.start_date >= args.end_date:
                    parser.error("--start-date must be earlier than --end-date")
                print(json.dumps({
                    "measurements": benchmark_queries(engine, args.start_date, args.end_date,
                                                       repetitions=args.repetitions),
                    "storage": database_sizes(engine),
                }, ensure_ascii=False, indent=2, default=str))
        finally:
            engine.dispose()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
