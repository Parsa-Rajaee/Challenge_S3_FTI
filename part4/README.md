# Part 4: Olist early-warning system (implementation candidate)

At order approval, assign a review-risk score to each Olist order and prioritize the top 10% for customer support. Negative feedback is a 1- or 2-star review. Olist data is re-used from the Stage 2 PostgreSQL schema.

## Run from repository root

Install Python 3.11+, PostgreSQL and dependencies:

```bash
python -m pip install -e ./part2/stage-2-database-performance
python -m pip install -e ./part4
export DATABASE_URL='postgresql+psycopg2://user:password@localhost:5432/fti'
python -m capstone.runner build --raw-dir part2/stage-2-database-performance/data/raw
python -m pytest part4/tests -q
```

Supply all nine Olist CSV files. Source CSVs are not committed. For Windows PowerShell use `$env:DATABASE_URL`. The `build` command calls Stage 2 migration and validated load functions, downloads/caches authentic Brazilian holidays, creates a PostgreSQL materialized view, trains logistic regression and random forest, and writes outputs to `part4/artifacts/`. Use `--skip-load` only after loading the authentic dataset; `--offline` uses a previously populated API cache.

## Output

- `follow_up_ranked.csv`: scored orders and Boolean top-10% follow-up flag.
- `evaluation.json`: held-out precision, recall, F1, AUC and confusion matrix for each capacity, monthly performance, drift and intentionally leaky comparison.
- `feature_query_plan.json`: measured SQL EXPLAIN plan.
- `timings.json`: runtime evidence; `ingestion_manifest.json`: ingestion counts/quarantine; `model.joblib`: trusted local model.

To score **precomputed feature schema** (not raw nine-table Olist order input):

```bash
fti-capstone predict --input new_features.csv --output part4/artifacts/unseen_ranked.csv
```

The CSV must contain `order_id`, `approved_at` and exactly the 22 columns in `capstone.core.FEATURES`. Invalid schemas are rejected.

## Release blockers

- Item, product, seller and payment attribute availability *at approval* is not timestamped by Olist. Those features are **not yet defensibly point-in-time safe**. A source-level SLA or removal is needed before production.
- Stage 1's ingestion contract handles NYC 311, not Olist; the pipeline deliberately reuses Stage 2's Olist loader, not a fictitious shared schema.
- A true new-raw-order schema entry point is not implemented.
- Full 45-minute cold-start runtime, feature-query sub-500ms target, regression tests for all stages, closed-holdout testing, and performance on full data are not yet verified.
- No fabricated model metrics or execution results are included.
