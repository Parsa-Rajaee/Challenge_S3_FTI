"""Command-line interface and inference module for Stage 3 Credit Risk ML.

Takes new applicant records with the project schema, loads the serialized
model artifact, and generates cost-optimal credit decisions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd

from .pipeline import CreditRiskPipeline, get_default_model_path


def predict_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    model_path: str | Path | None = None,
    threshold: float | None = None,
) -> pd.DataFrame:
    """Run batch credit risk inference on a data file."""
    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"Input file not found: {src}")

    if src.suffix.lower() == ".csv":
        df = pd.read_csv(src)
    elif src.suffix.lower() in (".json", ".jsonl"):
        df = pd.read_json(src, lines=src.suffix.lower() == ".jsonl")
    else:
        raise ValueError(f"Unsupported file format: {src.suffix}. Expected .csv or .json.")

    pipeline = CreditRiskPipeline.load(model_path)
    decisions = pipeline.predict_decisions(df, threshold=threshold)

    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        decisions.to_csv(out_file, index=False)
        print(f"Predictions successfully written to: {out_file.resolve()}")

    return decisions


def run_demo(model_path: str | Path | None = None) -> None:
    """Run an interactive demonstration using sample borrower profiles."""
    pipeline = CreditRiskPipeline.load(model_path)

    # 4 distinct representative customer archetypes
    sample_data = pd.DataFrame([
        {
            "applicant_id": 1001,
            "revolving_utilization_of_unsecured_lines": 0.08,
            "age": 55,
            "number_of_time30_59_days_past_due_not_worse": 0,
            "debt_ratio": 0.22,
            "monthly_income": 8500.0,
            "number_of_open_credit_lines_and_loans": 9,
            "number_of_times90_days_late": 0,
            "number_real_estate_loans_or_lines": 2,
            "number_of_time60_89_days_past_due_not_worse": 0,
            "number_of_dependents": 1,
        },
        {
            "applicant_id": 1002,
            "revolving_utilization_of_unsecured_lines": 0.88,
            "age": 24,
            "number_of_time30_59_days_past_due_not_worse": 2,
            "debt_ratio": 0.58,
            "monthly_income": 2800.0,
            "number_of_open_credit_lines_and_loans": 3,
            "number_of_times90_days_late": 0,
            "number_real_estate_loans_or_lines": 0,
            "number_of_time60_89_days_past_due_not_worse": 1,
            "number_of_dependents": 0,
        },
        {
            "applicant_id": 1003,
            "revolving_utilization_of_unsecured_lines": 0.45,
            "age": 42,
            "number_of_time30_59_days_past_due_not_worse": 98,  # Sentinel Code 98!
            "debt_ratio": 0.35,
            "monthly_income": 5200.0,
            "number_of_open_credit_lines_and_loans": 4,
            "number_of_times90_days_late": 98,
            "number_real_estate_loans_or_lines": 1,
            "number_of_time60_89_days_past_due_not_worse": 98,
            "number_of_dependents": 2,
        },
        {
            "applicant_id": 1004,
            "revolving_utilization_of_unsecured_lines": 0.25,
            "age": 36,
            "number_of_time30_59_days_past_due_not_worse": 0,
            "debt_ratio": 1250.0,
            "monthly_income": float("nan"),  # Missing income
            "number_of_open_credit_lines_and_loans": 6,
            "number_of_times90_days_late": 0,
            "number_real_estate_loans_or_lines": 1,
            "number_of_time60_89_days_past_due_not_worse": 0,
            "number_of_dependents": 1,
        },
    ])

    results = pipeline.predict_decisions(sample_data)
    print("\n" + "=" * 76)
    print(f"  STAGE 3 CREDIT RISK ML — INFERENCE DEMONSTRATION")
    print(f"  Cost-Optimal Threshold: {pipeline.optimal_threshold:.4f}  | Loss Matrix: FN=12, FP=1")
    print("=" * 76)
    print(
        f"{'Applicant':<12} {'Default Prob':<15} {'Predicted':<12} {'Risk Tier':<16} {'Decision':<10}"
    )
    print("-" * 76)
    for _, row in results.iterrows():
        print(
            f"{int(row['applicant_id']):<12} "
            f"{row['default_probability']:<15.4f} "
            f"{int(row['predicted_default']):<12} "
            f"{row['risk_tier']:<16} "
            f"{row['decision']:<10}"
        )
    print("=" * 76 + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for batch credit risk prediction."""
    parser = argparse.ArgumentParser(
        description="Predict credit risk default probabilities and cost-optimal decisions."
    )
    parser.add_argument(
        "-i", "--input", type=str, help="Path to input CSV / JSON dataset to predict."
    )
    parser.add_argument(
        "-o", "--output", type=str, help="Path to write output CSV predictions."
    )
    parser.add_argument(
        "-m", "--model-path", type=str, default=None, help="Path to trained model .joblib file."
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=None,
        help="Custom probability decision threshold (default: cost-optimal 0.0691).",
    )
    parser.add_argument(
        "--demo", action="store_true", help="Run demonstration on sample applicant profiles."
    )

    args = parser.parse_args(argv)

    if args.demo or (not args.input and not args.demo):
        run_demo(model_path=args.model_path)
        return 0

    try:
        predict_file(
            input_path=args.input,
            output_path=args.output,
            model_path=args.model_path,
            threshold=args.threshold,
        )
        return 0
    except Exception as exc:
        print(f"Error during credit risk inference: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
