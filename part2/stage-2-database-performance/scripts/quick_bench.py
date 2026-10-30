"""Print median timings and top plan nodes for each dashboard query (development helper)."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database_performance.benchmark import benchmark_queries  # noqa: E402

engine = create_engine(os.environ["DATABASE_URL"])
try:
    results = benchmark_queries(engine, date(2016, 9, 1), date(2018, 11, 1), repetitions=5)
finally:
    engine.dispose()


def nodes(plan, depth=0):
    label = plan["Node Type"] + (f" on {plan['Relation Name']}" if plan.get("Relation Name") else "")
    if plan.get("Index Name"):
        label += f" using {plan['Index Name']}"
    yield "  " * depth + f"{label} rows={plan['Actual Rows']} est={plan['Plan Rows']} ms={plan['Actual Total Time']}"
    for child in plan.get("Plans", []):
        yield from nodes(child, depth + 1)


for name, result in results.items():
    print(f"{name}: client median {result['client_median_ms']} ms, "
          f"server {result['server_execution_ms']} ms, planning {result['server_planning_ms']} ms")
    if "-v" in sys.argv:
        print("\n".join(nodes(result["server_plan"])))
