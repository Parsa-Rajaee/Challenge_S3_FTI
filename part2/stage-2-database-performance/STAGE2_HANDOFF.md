# Stage 2 handoff — validated current implementation

## Status and evidence

The current notebook is **successfully executed and saved**: 11 code cells, execution counts 1–11, no error outputs. The implementation includes the transactional loader, versioned migrations, final query/index choices, snapshot refresh, Python–SQL bridge, and an evidence-based `report.md`; the old unfinished-work checklist no longer describes it.

Sources of truth, relative to this stage:

- `solution.ipynb`: saved SQL, repeated timings, full plans, and experiment outputs.
- `data/curated/performance_results.json`: generated/Git-ignored results from that run; the saved notebook retains the evidence for delivery.
- `README.md` and `GETTING_STARTED.md`: installation and safe reproduction workflows.
- `STAGE2_EXPLAINED.md`: architecture/ERD, query semantics, transactions, and index decisions.

Check `git status`, the commit history, and `origin/master` for delivery status; this document records validation, not proof of a push or a completed PR.

## Exact saved results

PostgreSQL **16.15**; `work_mem=4MB`, `shared_buffers=128MB`, two parallel workers per gather; seed **42**. Purchase-date cohort **`[2016-09-01, 2018-11-01)`**. Times below are **client elapsed milliseconds**, with full result fetching: one warm-up, then five measured samples. Server `EXPLAIN` timings are recorded separately.

| Query | Selected implementation | Final median, ms | Final maximum, ms |
| --- | --- | ---: | ---: |
| Q1 monthly category revenue | Monthly snapshot | **4.345** | 6.482 |
| Q2 late delivery | Live | **130.165** | 141.324 |
| Q3 delay/reviews | Live; reviews averaged per order | **127.730** | 137.447 |
| Q4 top sellers | Live, set-based materialized CTEs; **not `LATERAL`** | **155.485** | 173.662 |
| Q5 payments | Live; independent payment/basket aggregates | **162.052** | 179.124 |

All final samples, including each maximum, are **below 200 ms**. Notebook runtime is **35.449 seconds excluding the 384.237-second initial load**, below the 600-second experiment budget. These are recorded observations, not production latency guarantees.

Important interpretation:

- Q1's live indexed baseline still takes **358.625 ms**; the selected snapshot is a non-index solution. Exact equality covers **1,264 full monthly-category rows**. Rebuilding all monthly snapshots takes **997.089 ms**, not that amount per month.
- Q4 already uses the current set-based formulation in its **148.181-ms primary-key-only baseline**. Historical `LATERAL` timings are not the current baseline or a measured speedup in this run.
- Q5's baseline is **271.367 ms**, indexed baseline **159.179 ms**, and rewritten-live phase **158.380 ms**. Indexes account for most of the observed reduction. Exact baseline/rewrite equality covers **28 result groups**.

## Final database decisions

- **Five retained secondary indexes:** `idx_order_items_seller`, `idx_order_reviews_order`, `idx_order_payments_order_method_cover`, `idx_order_items_order_value_cover`, and `idx_orders_order_purchase_cover`, in addition to primary-key indexes.
- **Six retired candidates:** `idx_geolocation_zip`, `idx_order_items_product`, `idx_order_payments_order`, `idx_orders_customer`, `idx_orders_delivered_purchase`, and `idx_products_category`. The experiment verifies their absence from indexed/rewrite plans before migrations `004` and `006` retire them; creation is tracked through migrations `003` and `005`.
- Olist-only index storage: **91,512,832 → 73,670,656 bytes** after retirement, a reduction of **17,842,176 bytes (17.02 MiB)**. Tables occupy **142,270,464 bytes (135.68 MiB)**. These are not whole-database/snapshot sizes. Geolocation's candidate is **7,274,496 bytes (6.94 MiB)** in this run; older size figures are not current.
- Isolated payment insert test: **50,000 rows**, three repetitions per configuration; median **68.378 ms** with PK only versus **103.628 ms** with the payment covering index (**1.516×**). This is not the write cost of the entire index set.
- Load: **1,550,922 source rows**, **1,550,885 accepted**, **37 unresolved-FK quarantines** (13 products lacking category translations, then 24 dependent items). Stage 1 loads **427,458 rows** through its own package into `nyc311.service_requests`.
- Bridge: **96,470 view rows** read in 20,000-row chunks and a final 16,470-row chunk; **27 state-summary rows** written with explicit dtypes.
- `analytics.delivery_delay_days` is this project's pure `IMMUTABLE STRICT PARALLEL SAFE` function. PostgreSQL **`VOLATILE` functions can write data**, but functions cannot manage transactions. `analytics.rebuild_monthly_snapshot` uses an advisory lock and atomic delete/insert **inside our caller's `engine.begin()` transaction**, with **no internal commit**. The saved idempotency example returns the same **43 January 2017 rows** twice; failure rollback is integration-tested.

## Validation and safe testing commands

Validated: **Stage 2: 48 tests pass, including PostgreSQL integration; Stage 1: 46 tests pass**. The empty-database guard is tested: it checks every existing Olist table, refuses fixture insertion if any contains rows, and cleans up without truncation. Integration fixtures and injected failures roll back. Without `DATABASE_URL`, database tests skip; that is not equivalent to the full passing run.

Use the pinned environment from `README.md` / `GETTING_STARTED.md`. All commands below run from the **repository root**. Credentials come **only from environment variables** in the launching process; provision `DATABASE_URL` through your local secret-management workflow. Do not paste passwords into commands/docs, print the URL, or store it in Git.

First point `DATABASE_URL` at a **dedicated empty test database**, separate from the loaded experiment and Stage 3:

```powershell
nyc311-db init-db
python -m unittest discover -s part2\stage-2-database-performance\tests -v
python -m unittest discover -s tests -v
```

For a complete build, switch the environment to a **disposable Stage 2 database** and supply both stages' inputs:

```powershell
nyc311-db build --raw-dir part2\stage-2-database-performance\data\raw --stage1-csv data\curated\curated_records.csv
```

To reproduce the experiment instead, with `DATABASE_URL` still targeting a disposable database:

```powershell
python part2\stage-2-database-performance\scripts\run_notebook.py
```

The notebook creates its own clean baseline; no prior build or manual reset is required. It **replaces `olist`, `analytics`, and `public.schema_migrations`**, and loads Stage 1 through its package. It does not reset `nyc311` or Stage 3's `credit` schema, but sharing their database is unsafe. The runner starts a fresh kernel and saves notebook outputs only after success; use `--kernel` if needed. Do not rerun merely to verify these docs: it replaces data and regenerates notebook/results artifacts.

## Caveats and follow-up boundaries

1. **Q1 freshness:** the snapshot needs explicit refresh after source changes; no automatic schedule is implemented. `load` clears but does not rebuild it; use `build` for a complete database. Q2–Q5 remain live.
2. **Benchmark scope:** five warmed samples on static data after `VACUUM (ANALYZE)` do not establish a cold-cache/concurrency SLA. Index-only scans had zero heap fetches in the saved plans; writes can change that. Rebenchmark with representative write/concurrent load before operational use.
3. **Index scope:** retired indexes may help other workloads/date ranges. Full-index-set write overhead and WAL volume remain unmeasured.
4. **Data completeness:** quarantined item revenue is excluded and unquantified. Decide whether/how to repair missing category translations; do not assume the financial impact is negligible.
5. **Atomicity scope:** the Olist replacement is one transaction, but the full multi-step build is not. Quarantine-file publication follows DB commit; a publication failure preserves its temporary file and requires follow-up.
6. **Delivery scope:** local validation is recorded here; confirm Git synchronization and any required submission/PR steps separately. No production-readiness claim is made.
