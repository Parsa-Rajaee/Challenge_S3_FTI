"""Time SQL files with bound parameters: median/min of N runs (development scratch tool)."""

from __future__ import annotations

import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

PARAMS = {"start_date": date(2016, 9, 1), "end_date": date(2018, 11, 1)}


def main(paths: list[str], reps: int = 9) -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        for path in paths:
            statement = text(Path(path).read_text(encoding="utf-8"))
            with engine.connect() as connection:
                connection.execute(statement, PARAMS).all()
                samples = []
                for _ in range(reps):
                    started = time.perf_counter()
                    rows = connection.execute(statement, PARAMS).all()
                    samples.append((time.perf_counter() - started) * 1000)
            print(f"{Path(path).name:40s} rows={len(rows):5d} median={statistics.median(samples):8.1f} "
                  f"min={min(samples):8.1f} max={max(samples):8.1f} ms")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1:])
