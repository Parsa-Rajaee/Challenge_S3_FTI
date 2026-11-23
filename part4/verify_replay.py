"""Replay the entire public holdout through the raw CSV prediction command."""
import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from capstone.runner import main

def verify(raw_dir, artifacts):
    report = json.loads((artifacts / "evaluation.json").read_text())
    plan = json.loads((artifacts / "feature_query_plan.json").read_text())[0]
    timings = json.loads((artifacts / "timings.json").read_text())
    assert plan["Execution Time"] < 500, f"Feature query took {plan['Execution Time']} ms"
    assert timings["total_seconds"] < 45 * 60, f"Build took {timings['total_seconds']} seconds"
    orders = pd.read_csv(raw_dir / "olist_orders_dataset.csv", dtype=str)
    approved = pd.to_datetime(orders["order_approved_at"])
    eligible = orders.loc[approved >= pd.Timestamp(report["cutoff_month"])].copy()
    # Outcomes are unavailable when a real approval event arrives.
    eligible["order_status"] = "approved"
    eligible["order_delivered_customer_date"] = ""
    eligible["order_delivered_carrier_date"] = ""
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "unseen.csv"
        ranking = Path(temp) / "ranked.csv"
        eligible.to_csv(source, index=False)
        main(["predict", "--offline", "--input", str(source), "--artifact", str(artifacts / "model.joblib"),
              "--output", str(ranking)])
        actual = pd.read_csv(ranking)
    expected = pd.read_csv(artifacts / "follow_up_ranked.csv")
    assert actual.order_id.tolist() == expected.order_id.tolist()
    assert actual.approved_at.tolist() == expected.approved_at.tolist()
    np.testing.assert_allclose(actual.risk_score, expected.risk_score, atol=1e-12, rtol=0)
    assert actual.follow_up.tolist() == expected.follow_up.tolist()
    assert actual.follow_up.is_monotonic_decreasing
    evidence = {
        "orders_matched": len(actual),
        "orders_flagged": int(actual.follow_up.sum()),
        "max_absolute_score_difference": float((actual.risk_score - expected.risk_score).abs().max()),
        "feature_query_budget_ms": 500,
        "build_budget_seconds": 45 * 60,
    }
    (artifacts / "replay.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Raw prediction replay matched all {len(actual)} public holdout orders.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("artifacts", type=Path)
    args = parser.parse_args()
    verify(args.raw_dir, args.artifacts)
