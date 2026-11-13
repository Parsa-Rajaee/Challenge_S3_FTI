# Stage 2 setup and reproducible execution

All commands below are PowerShell commands run from the **repository root**.
Keep the original Stage 3 database separate from the Stage 2 experiment.

## 1. Install the pinned environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e ".[database]"
python -m pip install -r part2\stage-2-database-performance\requirements.txt
python -m pip install -e .\part2\stage-2-database-performance
```

If the environment already exists, activate it instead of recreating it. Use its
interpreter/kernel in Jupyter. The Stage 1 and Stage 2 editable packages are both
required; Stage 2 loads Stage 1 output through `nyc311_factory.database`.

## 2. Start PostgreSQL

If the local container already exists:

```powershell
docker start season3-postgres
```

Otherwise choose a password interactively and create a local-only container:

```powershell
$password = Read-Host "Choose a local PostgreSQL password" -AsSecureString
$env:POSTGRES_PASSWORD = [System.Net.NetworkCredential]::new("", $password).Password
docker run --name season3-postgres -e POSTGRES_USER=season3 -e POSTGRES_PASSWORD -e POSTGRES_DB=olist -p 127.0.0.1:5432:5432 -d postgres:16
```

For an existing container, enter its existing password using the same two
PowerShell password-input lines. Never save a password or connection URL in Git.
After PostgreSQL is ready, create a disposable experiment database:

```powershell
docker exec season3-postgres pg_isready -U season3 -d olist
docker exec season3-postgres createdb -U season3 stage2_experiment
$encodedPassword = [uri]::EscapeDataString($env:POSTGRES_PASSWORD)
$env:DATABASE_URL = "postgresql+psycopg2://season3:${encodedPassword}@127.0.0.1:5432/stage2_experiment"
```

Create the database only once. If `stage2_experiment` already exists, reuse it
only if its `olist`/`analytics` contents may be replaced. Set `DATABASE_URL` in
the shell that launches Jupyter; the notebook will not guess credentials.

## 3. Supply both stages' inputs

Download the public [Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
and extract these files directly into `part2/stage-2-database-performance/data/raw/`:

```text
olist_customers_dataset.csv
olist_geolocation_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_orders_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
product_category_name_translation.csv
```

Also run Stage 1 using the repository's root README so
`data/curated/curated_records.csv` exists. Neither raw Olist data nor a manually
created database is a substitute for this chained package output.

## 4. Build or reproduce the experiment

For a complete database from empty PostgreSQL, after the input/setup steps:

```powershell
nyc311-db build --raw-dir part2\stage-2-database-performance\data\raw --stage1-csv data\curated\curated_records.csv
```

This command applies schema/index migrations, loads both data sources, rebuilds
monthly snapshots, and performs visibility-map maintenance. A missing Stage 1
CSV fails before replacing Olist data. `--skip-stage1` is for development only.
The lower-level `load` command clears old snapshots but does not rebuild them;
use `build` for the final dashboard.

For the measured submission, choose **Restart Kernel & Run All** on
`part2/stage-2-database-performance/solution.ipynb`, or run:

```powershell
python part2\stage-2-database-performance\scripts\run_notebook.py
```

**The notebook replaces `olist`, `analytics`, and `public.schema_migrations` in
the selected database.** It recreates a clean baseline on every run, so indexes
from a prior execution cannot contaminate the next one. Do not point it at the
original `olist` database used by Stage 3. No manual reset is needed.

The notebook records five warmed timing repetitions and full plans per query,
compares unchanged SQL before/after indexes, measures the Q5 rewrite separately,
verifies exact result equality, retires unused candidates, and selects the Q1
snapshot. It also measures index sizes, isolated bulk-insert overhead, chunked
view reads, explicit DataFrame dtypes, procedure idempotency, and total runtime.
Initial loading is reported separately from the ten-minute experiment limit.
Outputs are saved in the notebook and generated
`data/curated/performance_results.json`. Keep the notebook's outputs for delivery.

Q1's snapshot loses immediate freshness; call the monthly rebuild procedure after
changes, or rerun `build` for a complete refresh. Q2–Q5 are live SQL. Index-only
scan performance can degrade after writes until `VACUUM` updates visibility maps.

## 5. Run integration tests safely

Use a different, empty database; the tests refuse populated Olist tables:

```powershell
docker exec season3-postgres createdb -U season3 olist_test
$env:DATABASE_URL = "postgresql+psycopg2://season3:${encodedPassword}@127.0.0.1:5432/olist_test"
nyc311-db init-db
python -m unittest discover -s part2\stage-2-database-performance\tests -v
```

Create `olist_test` only once. Fixtures, temporary triggers, and injected errors
are transactionally rolled back. Tests cover payment grouping, missing baskets,
shared seller orders, multiple reviews, snapshot freshness/idempotency, and
mid-insert failure rollback. Without `DATABASE_URL`, integration tests skip;
a passing offline-only suite is not proof the SQL works.

Return `DATABASE_URL` to `stage2_experiment` before rerunning the notebook. The
Stage 1 tests remain available from the repository root:

```powershell
python -m unittest discover -s tests -v
```

## Troubleshooting

- **Missing environment variable:** set `DATABASE_URL` before launching Jupyter.
- **Wrong kernel/packages:** select the activated venv; the runner also accepts `--kernel`.
- **Docker unavailable:** start Docker Desktop, then the existing PostgreSQL container.
- **Missing CSV:** extract all nine files directly into the expected raw folder.
- **Missing Stage 1 output:** run Stage 1; the final build intentionally fails rather than silently omitting it.
- **Integration isolation error:** select an empty test database; do not truncate a database you need.
- **Over-budget query:** inspect the saved plan and samples. Never replace the measured value with a faster number from another run.
