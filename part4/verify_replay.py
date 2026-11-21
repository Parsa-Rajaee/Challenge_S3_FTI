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
        main(["predict", "--input", str(source), "--artifact", str(artifacts / "model.joblib"),
              "--output", str(ranking)])
        actual = pd.read_csv(ranking)
    expected = pd.read_csv(artifacts / "follow_up_ranked.csv")
    assert actual.order_id.tolist() == expected.order_id.tolist()
    np.testing.assert_allclose(actual.risk_score, expected.risk_score, atol=1e-12)
    assert actual.follow_up.tolist() == expected.follow_up.tolist()
    print(f"Raw prediction replay matched all {len(actual)} public holdout orders.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("artifacts", type=Path)
    args = parser.parse_args()
    verify(args.raw_dir, args.artifacts)
