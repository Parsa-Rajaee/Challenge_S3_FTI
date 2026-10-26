"""Command-line entry point for the NYC 311 data factory."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__
from .analytics import build_analysis_outputs, load_population
from .api import SocrataClient
from .config import Settings, load_settings
from .curation import curate_raw_pages
from .exceptions import DataValidationError, FactoryError
from .factory import run_factory
from .pipeline import RawDownloader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the configured NYC 311 analytical dataset"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.json"),
        help="Path to the project JSON configuration",
    )
    # The four run modes are mutually exclusive: only one can be chosen per run.
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--count-only",
        action="store_true",
        help="Count matching source records without downloading them",
    )
    modes.add_argument(
        "--download-only",
        action="store_true",
        help="Download and checkpoint raw pages only",
    )
    modes.add_argument(
        "--curate-only",
        action="store_true",
        help="Validate existing raw pages and write curated outputs",
    )
    modes.add_argument(
        "--analyze-only",
        action="store_true",
        help="Join existing curated records to the population reference",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Reprocess a complete local checkpoint without making source requests",
    )
    parser.add_argument(
        "--rolling-window-days",
        type=int,
        help=(
            "Use a rolling incremental date window. The first run looks back this "
            "many days; later runs start from the previous successful end date."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Read the command-line flags, then load the JSON config.
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.offline and any(
            (args.count_only, args.download_only, args.curate_only, args.analyze_only)
        ):
            raise DataValidationError("--offline can only be used with the full factory")
        if args.offline and args.rolling_window_days is not None:
            raise DataValidationError("--offline cannot be combined with rolling-window mode")
        # Rolling mode changes the date range, so apply it before anything else runs.
        if args.rolling_window_days is not None:
            if args.rolling_window_days < 1:
                raise DataValidationError("--rolling-window-days must be at least 1")
            settings, rolling_state = _rolling_settings(
                settings,
                args.rolling_window_days,
            )
        else:
            rolling_state = None

        # Curated and analytical outputs go to output_dir (default: data/curated).
        output_dir = settings.output_dir or settings.raw_dir.parent.parent / "curated"
        # Run exactly one step, depending on the mode flag. Each returns a summary dict.
        if args.count_only:
            result = {
                "matching_records": SocrataClient(settings).count_matching_records()
            }
        elif args.download_only:
            result = RawDownloader(settings).run()
        elif args.curate_only:
            result = curate_raw_pages(settings, output_dir)
        elif args.analyze_only:
            population = load_population(settings.population_path)
            result = build_analysis_outputs(
                settings,
                output_dir / "curated_records.csv",
                population,
                output_dir,
            )
        else:
            # Full pipeline. The rolling state is saved only after the whole run succeeds.
            result = run_factory(settings, offline=args.offline)
            if rolling_state is not None:
                _write_rolling_state(rolling_state[0], rolling_state[1])

        # Print the summary as formatted JSON.
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except FactoryError as exc:
        # Expected errors print a one-line message and return their exit code (2-5).
        # Unexpected errors are not caught here, so they still show a full traceback.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return exc.exit_code


# Rolling mode: each run covers from the previous run's end date up to tomorrow.
# The state file records that end date only after the run succeeds.
def _rolling_settings(
    settings: Settings,
    lookback_days: int,
) -> tuple[Settings, tuple[Path, date]]:
    now = datetime.now(UTC)
    end_date = now.date() + timedelta(days=1)
    state_path = settings.raw_dir.parent / "rolling_state.json"
    if state_path.is_file():
        try:
            state: Any = json.loads(state_path.read_text(encoding="utf-8"))
            start_date = date.fromisoformat(state["last_end_date"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DataValidationError(
                f"Cannot use rolling-window state {state_path}: {exc}"
            ) from exc
    else:
        start_date = end_date - timedelta(days=lookback_days)
    if start_date >= end_date:
        raise DataValidationError(
            f"Rolling window start {start_date} is not earlier than end {end_date}"
        )

    # Each window gets its own raw folder so windows never mix or overwrite each other.
    window_dir = settings.raw_dir / "rolling" / f"{start_date}_{end_date}"
    # replace() copies the frozen Settings object and changes only the listed fields.
    rolling_settings = replace(
        settings,
        start_date=start_date,
        end_date=end_date,
        raw_dir=window_dir,
        checkpoint_path=window_dir / "checkpoint.json",
        # Incremental windows can legitimately be small, so the minimum-row check is turned off.
        target_min_records=0,
    )
    return rolling_settings, (state_path, end_date)


def _write_rolling_state(path: Path, end_date: date) -> None:
    # Write to a temp file, then rename, so the state file is never left half-written.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"last_end_date": end_date.isoformat()}, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
