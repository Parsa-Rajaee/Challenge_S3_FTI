# Olist early warning

From the repository root, install Python 3.12, PostgreSQL and the packages:

```sh
python -m pip install -r part4/requirements.txt -e . -e ./part2/stage-2-database-performance -e ./part4
```

Set `DATABASE_URL` to a dedicated disposable PostgreSQL database. A build replaces its Olist tables. Download and unzip all nine CSVs from the [public Olist distribution](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) into the Stage 2 raw folder. From an empty database run the build and verify public replay:

```sh
fti-capstone build --raw-dir part2/stage-2-database-performance/data/raw
python part4/verify_replay.py part2/stage-2-database-performance/data/raw part4/artifacts
jupyter nbconvert --to notebook --execute --inplace part4/*.ipynb
```

On PowerShell use `$env:DATABASE_URL`. Nager.Date provides Brazilian holidays. For offline replay, copy part4/data/external from a successful build and add --offline. Use only trusted model files.

Load recent events into the reference database, refresh its aggregates and score a new Olist orders CSV with all original headers, including nullable fields:

```sh
fti-capstone refresh-reference
fti-capstone predict --input new_orders.csv --output ranked.csv
python -m pytest part4/tests -q
```

Raw scoring uses the ingestion field parsers and the same SQL as training. Unknown customer locations use `UNKNOWN`, missing approvals are excluded, and invalid schemas or duplicate IDs raise an error. Precomputed inputs must match the feature contract. Ties go to the earliest approval, then the lowest order ID. Use `predict --offline` to score from cached holiday calendars. Set `CAPSTONE_TEST_DATABASE_URL` to a separate empty database to run the synthetic raw-to-ranking test.

Open [solution.ipynb](solution.ipynb) for the system and [01_exploration.ipynb](01_exploration.ipynb) for the feature analysis. Both contain saved public-data results. To run from a fresh checkout without building first, set `FTI_CAPSTONE_RAW_DIR` to the absolute path of the extracted CSVs and `DATABASE_URL` to a disposable database before starting the notebook. The first notebook builds the evidence and the other reuses it. The build and replay write the ranked list, model, metrics, SQL plan, timings and operations brief to `part4/artifacts`. The [report](report.md) explains the methodology and results.

### Optional commercial data

For a system with versioned checkout data, add `--checkout-snapshots snapshots.csv` to the build. Each CSV row is one complete observed basket. Use columns `order_id,observed_at,seller_count,product_count,observed_payment_value,interstate_shipping`. Count distinct sellers and products in the captured basket, sum payment values visible at that instant and set interstate_shipping when any captured seller and buyer states differ. Use the actual observation time in Olist local time. The query selects the latest qualifying snapshot per order and ignores later snapshots. A build without this file reports zero coverage and learns from the other inputs. Do not invent observation times for the public export.

The supplied `part4/sql/capture_checkout.sql` builds that CSV from observed order items, sellers, products, payments and checkout geography in a live database. Run it in a transaction-consistent SQL session with CSV output and retain each capture's timestamp. Applying it to a historical dump today cannot recreate past checkout observations. To update live scoring, pass the full accumulated history to `fti-capstone refresh-reference --checkout-snapshots snapshots.csv`. A refresh without that argument keeps the stored snapshots.
