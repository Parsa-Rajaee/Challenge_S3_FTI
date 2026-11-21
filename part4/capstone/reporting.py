"""Write a short operations brief from the actual build results."""
import json

def write_reports(output):
    data = json.loads((output / "evaluation.json").read_text())
    timings = json.loads((output / "timings.json").read_text())
    plan = json.loads((output / "feature_query_plan.json").read_text())[0]
    name = data["model_selected"]
    metrics = data["metrics"]
    lines = ["# Customer support follow-up", "",
             "Start with the flagged orders in follow_up_ranked.csv. Contact at most one order in ten. "
             "A flag means an order merits a check-in. It does not establish that a customer is dissatisfied.", "",
             "| Share contacted | Negative reviews found | Flagged orders with a known review that was negative |",
             "|---|---:|---:|"]
    for capacity in ("0.05","0.1","0.2"):
        result = metrics[name][capacity]
        lines.append(f"| {float(capacity):.0%} | {result['recall']:.1%} | {result['precision']:.1%} |")
    last = data["last_month"]["recall"]
    latest = "no known outcomes" if last is None else f"{last:.1%} of known negative reviews found"
    lines.extend(["", f"Latest month ({max(data['monthly'])}): {latest}.",
                  "Customers who leave no review have unknown outcomes. Start by comparing a small randomly assigned outreach group with usual service before drawing conclusions about impact."])
    (output / "operations_summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    lines = ["# Measured results", "", *lines[4:9],
             "", f"Selected family: {name}. Boundary: {data['cutoff_month']}.",
             f"Simple approval-delay rule recall: {metrics['approval_delay_baseline']['0.1']['recall']:.2%}.",
             f"Leaky comparison minus selected model recall: {data['leakage_recall_delta_at_10pct']:+.2%}.",
             f"Holiday contribution to recall: {metrics[name]['0.1']['recall']-metrics['without_holiday']['0.1']['recall']:+.2%}.",
             f"Full feature SELECT: {plan['Execution Time']:.1f} ms. Build: {timings['total_seconds']:.1f} seconds.",
             "", "See evaluation.json for the confusion counts, each month's sample size and drift by feature."]
    latest_month = max(data["monthly"])
    latest = data["monthly"][latest_month]
    lines.extend(["", f"Last month: {latest_month}, {latest['eligible_orders']} eligible orders, "
                       f"{latest['n']} reviewed, {latest.get('positives', 0)} negative.",
                  f"Known-outcome recall: {latest['recall']}.",
                  f"Missing approvals excluded: {data['approved_timestamp_missing_excluded']}."])
    (output / "measured_results.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
