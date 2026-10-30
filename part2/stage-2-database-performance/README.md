# Stage 2 — Database Performance

New to SQL? Start with [`GETTING_STARTED.md`](GETTING_STARTED.md), which explains every setup step and database term.

## Quick setup (PowerShell, from the project root)

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e ".[database]"
python -m pip install -e .\part2\stage-2-database-performance
```

Start Docker Desktop, download the nine Olist CSV files into `part2/stage-2-database-performance/data/raw/`, and set `DATABASE_URL` in the same shell; the detailed instructions and PowerShell commands are in `GETTING_STARTED.md`.

## Database commands (from the project root)

```powershell
# From an empty PostgreSQL database, one command creates the tables and loads Olist.
nyc311-db load --raw-dir part2\stage-2-database-performance\data\raw

# For a clean, repeatable Notebook baseline, reset the Stage 2 schemas first.
nyc311-db init-db --reset
```

The load command also upserts Stage 1's `data/curated/curated_records.csv` into `nyc311.service_requests` when that file exists; pass `--skip-stage1` to omit it. `--reset` drops only the Stage 2 `olist` and `analytics` schemas. It is destructive to those schemas; do not use it where their data must be kept. The loader replaces Olist rows in one transaction and writes rejected rows to `part2/stage-2-database-performance/data/curated/integrity_quarantine.jsonl`.

Open `solution.ipynb` and run **Restart Kernel & Run All** to collect query plans, repeatable timings, write-cost comparisons, per-index sizes, and the view/snapshot comparison. The notebook expects a fresh baseline (no candidate indexes); reset the local schemas before each full experiment. It checks plan evidence before applying the versioned migration that drops the unused geolocation index. The 200 ms target is not claimed until a real PostgreSQL run confirms it.

Run the Stage 2 tests from this directory:

```powershell
python -m unittest discover -s tests -v
```

Offline schema tests always run. PostgreSQL integration tests need `DATABASE_URL` and initialized migrations. The original Stage 1 package remains at the project root; install it with the database extra and use `nyc311-factory --load-curated-to-database` to send its curated CSV to PostgreSQL.
