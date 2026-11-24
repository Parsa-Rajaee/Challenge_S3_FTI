"""Write a short operations brief from the actual build results."""
import json


def percent(value):
    return "—" if value is None else f"{value:.1%}"


def write_reports(output):
    data = json.loads((output / "evaluation.json").read_text())
    timings = json.loads((output / "timings.json").read_text())
    plan = json.loads((output / "feature_query_plan.json").read_text())[0]
    name = data["model_selected"]
    metrics = data["metrics"]
    capacity_rows = [
        "| Contact limit | Flagged | Flagged with reviews | Known negative reviews found | Precision among reviewed alerts |",
        "|---|---:|---:|---:|---:|",
    ]
    for capacity in ("0.05", "0.1", "0.2"):
        result = metrics[name][capacity]
        capacity_rows.append(
            f"| {float(capacity):.0%} | {result['total_flagged']:,} | {result['selected']:,} "
            f"| {percent(result['recall'])} | {percent(result['precision'])} |"
        )
    main_result = metrics[name]["0.1"]
    latest_month = max(data["monthly"])
    latest = data["monthly"][latest_month]
    last_month = (
        f"In {latest_month}, the 10% limit allowed {latest['total_flagged']:,} contacts. "
        f"Eligible orders totaled {latest['eligible_orders']:,}. "
        f"Of those, {latest['n']:,} had reviews and {latest['positives']:,} had negative reviews."
    )
    if latest["recall"] is not None:
        last_month += f" The list found {percent(latest['recall'])} of those orders."
    operations = [
        "# Customer support follow-up",
        "",
        "Start at the top of the ranked list and contact the flagged customers. "
        "Use the list to offer order updates and log whether customers needed help.",
        "",
        f"The public holdout contained {main_result['eligible_orders']:,} eligible orders "
        f"and {main_result['n']:,} had reviews. Orders without reviews still count toward the contact limit.",
        "",
        *capacity_rows,
        "",
        last_month,
        "",
        "Compare a small, randomly assigned outreach group with usual service to measure whether contacting customers helps.",
    ]
    (output / "operations_summary.md").write_text("\n".join(operations) + "\n", encoding="utf-8")
    baseline_recall = metrics["approval_delay_baseline"]["0.1"]["recall"]
    holiday_recall = metrics["without_holiday"]["0.1"]["recall"]
    lines = [
        "# Measured results",
        "",
        *capacity_rows,
        "",
        f"The {name} model was selected using {len(data['validation_folds'])} chronological "
        f"validation months. The holdout starts in {data['cutoff_month']}.",
        f"The approval-delay rule found {baseline_recall:.2%} of known negative reviews at 10% capacity.",
        f"Adding future information changed recall by {100 * data['leakage_recall_delta_at_10pct']:+.2f} percentage points.",
        f"The holiday flag changed recall by {100 * (main_result['recall'] - holiday_recall):+.2f} percentage points.",
        f"The full feature query ran in {plan['Execution Time']:.1f} ms and the build took {timings['total_seconds']:.1f} seconds.",
        "",
        last_month,
        f"Excluded {data['approved_timestamp_missing_excluded']:,} orders with missing approvals.",
        "See evaluation.json for confusion counts, monthly results and drift by feature.",
    ]
    numeric_drift = {}
    for feature, change in data["drift"].items():
        shift = change.get("standardized_mean_shift")
        if shift is not None:
            numeric_drift[feature] = shift
    for feature in sorted(numeric_drift, key=numeric_drift.get, reverse=True)[:3]:
        lines.append(f"The mean of {feature} shifted by {numeric_drift[feature]:.2f} training standard deviations.")
    lines.append(f"Timestamped commercial snapshots covered {data['snapshot_coverage']:.1%} of approvals.")
    (output / "measured_results.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
