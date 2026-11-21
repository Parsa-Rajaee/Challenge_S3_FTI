# Olist early warning

From the repository root, install Python 3.12, PostgreSQL and the packages:

```sh
python -m pip install -e . -e ./part2/stage-2-database-performance -e ./part4 pytest
```

Set DATABASE_URL to a dedicated disposable PostgreSQL database. A build replaces its Olist tables. Put all nine CSVs from the public olistbr/brazilian-ecommerce distribution in the Stage 2 raw folder. From an empty database run:

```sh
fti-capstone build --raw-dir part2/stage-2-database-performance/data/raw
```

On PowerShell use `$env:DATABASE_URL`. Nager.Date provides Brazilian holidays. For offline replay, copy part4/data/external from a successful build and add --offline. Use only trusted model files.

Score a new Olist orders CSV with all original headers, including nullable fields:

```sh
fti-capstone predict --input new_orders.csv --output ranked.csv
python -m pytest part4/tests -q
```

Raw scoring uses the ingestion field parsers and the same SQL as training. Keep the reference database current. Unknown customer locations use UNKNOWN, missing approvals are excluded, and invalid schemas or duplicate IDs raise an error. Existing precomputed inputs must match the new feature contract exactly. Retrain older models. Set CAPSTONE_TEST_DATABASE_URL to a separate empty database to run the synthetic raw-to-ranking test.

Open 01_exploration.ipynb and 02_system.ipynb after the build. The ranked list, model, evaluation, SQL plan, timings, ingestion evidence, measured results and operations brief appear in part4/artifacts. See feature_audit.md, decisions.md and report.md for interpretation.
