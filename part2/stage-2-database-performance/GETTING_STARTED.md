# Stage 2: what to do, step by step

This guide assumes you are new to SQL. Follow the numbered steps in order. **Do not worry about tuning the database first**: the notebook will measure a simple version, add candidate indexes, then measure again.

## What is this project?

You are building a small PostgreSQL database for the public Brazilian Olist online-shop data. You will load its nine CSV files, write five useful questions as SQL, and compare query plans and timings before and after indexing. The Stage 1 NYC 311 package also gets a PostgreSQL destination; Stage 2 must use that existing package rather than a separate one-off loader.

The main deliverables are:

- `solution.ipynb`: the story and the measured experiments.
- `report.md`: why you made the choices, based on evidence from the notebook.
- `sql/migrations/`: version-controlled table, view, function, procedure, and index definitions.
- `sql/queries/`: the five dashboard questions.
- `src/`: reusable Python loader and timing code.
- `tests/`: checks that the design and SQL return the expected answers.

## Step 1 — Open PowerShell at the project root

The project root is the folder that contains `pyproject.toml`, `config/`, and `part2/`. All commands below are run from that folder unless a step says otherwise.

```powershell
.\.venv\Scripts\Activate.ps1
```

If `.venv` does not exist yet, create it first:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the pinned packages and both editable projects. This installs the Stage 1 `nyc311-factory` command and the Stage 2 `nyc311-db` command into the same environment:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e ".[database]"
python -m pip install -r part2\stage-2-database-performance\requirements.txt
python -m pip install -e .\part2\stage-2-database-performance
```

## Step 2 — Start PostgreSQL

Install and start Docker Desktop if you do not already have PostgreSQL. In PowerShell, create a local PostgreSQL container:

```powershell
$env:POSTGRES_PASSWORD = "1234"
docker run --name season3-postgres -e POSTGRES_USER=season3 -e POSTGRES_PASSWORD -e POSTGRES_DB=olist -p 127.0.0.1:5432:5432 -d postgres:16
```

Keep the password in your terminal's environment, not in a source file. Set the connection string in that same PowerShell window:

```powershell
$encodedPassword = [uri]::EscapeDataString($env:POSTGRES_PASSWORD)
$env:DATABASE_URL = "postgresql+psycopg2://season3:${encodedPassword}@localhost:5432/olist"
docker exec season3-postgres pg_isready -U season3 -d olist
```

If you already created the container, start it instead of running `docker run` again:

```powershell
docker start season3-postgres
```

A successful readiness check says that PostgreSQL is accepting connections. The database is local; do not commit your password or `DATABASE_URL`.

## Step 3 — Get the nine Olist CSV files

Download and unzip the Brazilian E-Commerce Public Dataset by Olist from Kaggle. Put the CSV files directly in `part2/stage-2-database-performance/data/raw/`. No Kaggle API key is needed if you download them in a browser.

The expected names are:

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

The files are raw inputs and are ignored by Git. Never rename columns to make a load succeed; report an unexpected header instead.

## Step 4 — Create an empty Stage 2 database

**This reset deletes the `olist` and `analytics` schemas in this local database.** It does not delete the separate `nyc311` schema. Run it only in your local development database, not a database that contains data you need.

```powershell
nyc311-db init-db --reset
```

The command runs the SQL migrations and creates the nine typed Olist tables and analytics views. The candidate dashboard indexes are deliberately not created yet, so the first measurement can be a genuine baseline.

## Step 5 — Run the notebook

Open `part2/stage-2-database-performance/solution.ipynb` in Jupyter or VS Code, select the Python interpreter from the activated `.venv`, and choose **Restart Kernel & Run All**. The notebook checks `DATABASE_URL` and the CSV folder, then:

1. Loads the nine files inside one database transaction. Invalid rows go to `data/curated/integrity_quarantine.jsonl`; a failed database write rolls back.
2. Measures all five queries and captures PostgreSQL `EXPLAIN ANALYZE` plans before candidate indexes.
3. Builds candidate indexes and reloads the same source files to compare insert time before and after indexes.
4. Measures the queries again, records index/table sizes, and compares a live view with a monthly snapshot.
5. Writes the machine-readable measurements to `data/curated/performance_results.json`.

Loading Olist replaces the Stage 2 Olist tables. The notebook does not silently reset your database; use Step 4 when you intentionally want a clean baseline. The notebook can also upsert existing Stage 1 curated records into `nyc311.service_requests` when `data/curated/curated_records.csv` is available.

## Step 6 — Run tests

From the Stage 2 folder, with the same environment activated:

```powershell
python -m unittest discover -s tests -v
```

The schema tests run offline. PostgreSQL integration tests are skipped until `DATABASE_URL` is set. To run them against a dedicated clean test database without interference from loaded Olist data:

```powershell
docker exec season3-postgres createdb -U season3 olist_test
$env:DATABASE_URL = "postgresql+psycopg2://season3:1234@localhost:5432/olist_test"
nyc311-db init-db
python -m unittest discover -s tests -v
```

The integration tests create sample rows inside a transaction and roll them back when each test finishes.

The Stage 1 test suite still runs from the project root:

```powershell
python -m unittest discover -s tests -v
```

## Step 7 — Read the output, then write the report

Start with the five query files in `sql/queries/`. For each query, compare its baseline and indexed median time **and** its plan. In a plan, `Seq Scan` means PostgreSQL read a table one row at a time; `Index Scan` means it used an index to find rows; `actual rows` and `Plan Rows` let you compare real work with the estimate. An index is not automatically a win: it takes disk space and makes inserts slower.

Use the actual numbers written by the notebook to finish `report.md`. In particular, record:

- Why each index helped, did not help, or was removed, with plan evidence.
- All five timing results and the repeatable measurement method.
- The measured increase in load time and index size.
- The live-view versus snapshot timings and their freshness/maintenance trade-off.
- Any invalid rows and unresolved foreign keys in the quarantine counts.
- At least one failed or discarded approach, if you actually tried one.
- An `AI usage` note. This guide and some starter code were drafted with AI; verify each choice yourself and update the note to accurately describe what you changed and tested.

**Never invent timings or say a query meets the 200 ms budget until PostgreSQL actually ran it and the saved notebook output shows the result.** The database is not currently available in this workspace, so those performance results are not filled in for you.

## If something goes wrong

- **`DATABASE_URL` missing:** set it in the same PowerShell window used to launch Jupyter.
- **Docker pipe/engine error:** open Docker Desktop and wait for it to finish starting. 
- **CSV missing:** extract all nine files directly into `data/raw/`; do not put them in an extra nested folder.
- **Missing table/schema:** run `nyc311-db init-db --reset`, then restart the notebook.
- **SQLAlchemy or `nyc311-db` not found:** activate `.venv` and repeat Step 1.
- **A query is over 200 ms:** that is useful evidence, not a reason to make up a result. Compare its plan with and without indexes, investigate the largest scan/join, and document what you try.
