# Stage 2 — Database Performance

Run these setup and build commands from the **repository root**, using Python 3.11+:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e ".[database]"
python -m pip install -r part2\stage-2-database-performance\requirements.txt
python -m pip install -e .\part2\stage-2-database-performance
```

Provide the nine Olist CSVs in `part2/stage-2-database-performance/data/raw/`
and Stage 1's `data/curated/curated_records.csv`. Raw inputs are not committed.
Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL in the launching shell; no
credentials are embedded in the notebook.

## Build from an empty database

```powershell
nyc311-db build --raw-dir part2\stage-2-database-performance\data\raw --stage1-csv data\curated\curated_records.csv
```

This applies versioned migrations and final indexes, transactionally loads Olist,
loads Stage 1 through its original package, rebuilds all monthly snapshots, and
runs `VACUUM (ANALYZE)` for the static imported tables. Missing Stage 1 input is
an error unless you explicitly request `--skip-stage1` (not a complete submission).
`load` alone does **not** populate the dashboard snapshot; use `build`.

## Reproduce the notebook

**Use a separate disposable database.** The notebook intentionally replaces its
`olist` and `analytics` schemas and `public.schema_migrations`, then builds a
primary-key-only baseline. It does not reset `nyc311` or Stage 3's `credit` schema,
but sharing the experiment database with other stages is not recommended.

Open `solution.ipynb` with the pinned environment and **Restart Kernel & Run All**, or:

```powershell
python part2\stage-2-database-performance\scripts\run_notebook.py
```

The runner starts a fresh kernel and saves outputs only after success. Use
`--kernel <installed-kernel-name>` if `python3` is not your pinned environment.
The notebook saves SQL, repeated timings, complete before/after plans, index
sizes, insert costs, result-equivalence checks, and runtime in its outputs and
`data/curated/performance_results.json`. The JSON is generated/ignored; the
executed notebook is the committed evidence.

Q1 uses the monthly snapshot and must be refreshed after source changes. Q2–Q5
remain live. Q5's index-only scans assume visibility-map maintenance; benchmark
again after substantial writes. The report distinguishes median and worst
observed sample rather than promising a production latency SLA.

## Tests

Point `DATABASE_URL` at a **different empty test database**, initialize it, then:

```powershell
nyc311-db init-db
python -m unittest discover -s part2\stage-2-database-performance\tests -v
```

Tests roll back fixtures and refuse to touch an Olist database containing rows.
Without `DATABASE_URL`, database integration tests are explicitly skipped.
