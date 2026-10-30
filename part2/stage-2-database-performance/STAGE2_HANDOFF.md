# Stage 2 handoff: findings, evidence and remaining work

Status: **Stage 2 is not finished.** The loader, schema, views, function, procedure and the five base queries already existed. This session got a real PostgreSQL running and measured the real data. The notebook has not been re-run, `report.md` is still a placeholder draft, and several PDF requirements are still missing (section 4).

Source requirements: `part2/PDF_CONTENT.md` (extracted text of `02_Challenge_Database_Performance.pdf` and the shared delivery guide).

## 1. Environment, what is running now

- Docker Desktop was started with `docker desktop start`; the engine is up.
- A container named `season3-postgres` (image `postgres:16`, PostgreSQL 16.15, bound to `127.0.0.1:5432`, DB `olist`, user `season3`) already existed from an earlier session. I started it and did **not** delete or recreate it. It has 8 cores available, `work_mem=4MB`, `shared_buffers=128MB` (defaults).
- The DB already contains a full Olist load (counts below), the `analytics` views, the function and the procedure. `analytics.monthly_category_snapshot` is empty.
- `ipykernel==6.29.5` was pip-installed into `.venv` (it is already pinned in this stage's `requirements.txt`). You may still need a kernelspec named `python3` (`python -m ipykernel install --user --name python3`) before `nbclient` can run the notebook.
- I never read or printed the DB password. `scripts/with_local_db.py` reads it from the container config and injects `DATABASE_URL` into a child process only.

Run anything against the local DB like this (PowerShell, from this folder):

```powershell
$py = "E:\Parsa\Season_3_project\.venv\Scripts\python.exe"
& $py scripts\with_local_db.py & $py scripts\inspect_db.py                       # list relations + row counts
& $py scripts\with_local_db.py & $py scripts\quick_bench.py -v                   # 5 queries: timings + plan nodes
& $py scripts\with_local_db.py & $py -m unittest discover -s tests -v            # tests
```

Current row counts in the DB: customers 99,441; orders 99,441; order_items 112,626; order_payments 103,886; order_reviews 99,224; products 32,938; sellers 3,095; geolocation 1,000,163; category_translations 71.

## 2. Warnings, read before touching the DB

1. **I applied `sql/migrations/003_candidate_indexes.sql` by hand with psql.** The 8 candidate indexes exist now, but `public.schema_migrations` only lists `001` and `002`. If the notebook calls `apply_migrations(include_indexes=True)` it will fail with "already exists". Run `nyc311-db init-db --reset` (drops only the `olist` and `analytics` schemas and `schema_migrations`) before any full notebook run, then reload. The reload takes several minutes.
2. The 6 integration tests that fail on this DB do not show a bug in the SQL. They assume empty tables and are polluted by the loaded Olist data. Run them against a separate empty database, for example `docker exec season3-postgres createdb -U season3 olist_test`, then `init-db` and the tests with a `DATABASE_URL` that points at `olist_test`. Make the tests fail loudly if they are pointed at a non-empty DB.
3. The scratch tool `scripts/lab/index_lab.py` creates temporary `t_*` indexes and drops them in a `finally` block. Confirm none leaked: `SELECT indexname FROM pg_indexes WHERE schemaname='olist' AND indexname LIKE 't\_%'`.
4. Nothing was committed. `part2/` is untracked in Git. The guide wants at least 8 meaningful English commits, a feature branch and a PR. The stage folder must be delivered as `stage-2-<your-name>/`.

## 3. Measured evidence (real numbers, local Docker PostgreSQL 16.15)

Parameters: full range 2016-09-01 to 2018-11-01. Times are client medians in ms, including fetching results, except where noted. Run-to-run noise is about 10-15%; use at least 9 repetitions and report medians.

### 3.1 Baseline (no candidate indexes) and after the 8 candidate indexes (`quick_bench.py`, 5 reps)

| Query | Baseline client | Baseline server | After 003 indexes client | Verdict |
| --- | --- | --- | --- | --- |
| 01 monthly revenue | 394 | 481 | 368 | over budget, indexes do nothing |
| 02 late delivery | 130 | 145 | 120 | ok |
| 03 delay vs reviews | 226 | 290 | 190 | index helped |
| 04 top sellers | 967 | 1400 | 994 | far over budget, indexes do nothing |
| 05 payments | 426 | 392 | 351 | over budget |

Plans after the 003 indexes show only two indexes used: `idx_order_reviews_order` (Index Only Scan for Q3 and Q4; the review aggregate dropped from about 92 ms to about 57 ms) and `idx_order_payments_order` (Q5; it is redundant with the primary key `(order_id, payment_sequential)`). So **6 of the 8 candidates were not used by any of the five plans**: `idx_orders_delivered_purchase`, `idx_orders_customer`, `idx_order_items_seller`, `idx_order_items_product`, `idx_products_category`, `idx_geolocation_zip`. Re-check this against the final query set and the plans before dropping them.

### 3.2 Why each query is slow (plan reading)

- **Q1** (`analytics.monthly_category_revenue` view, `sql/queries/01_monthly_revenue.sql`). The date filter is applied to `date_trunc('month', order_purchase_timestamp)::date`, a computed output column of the view. It is not sargable, so it becomes a `Filter:` on a Seq Scan of `orders`. The plan then runs a nested loop with **96,478 index probes** into `order_items_pkey` (about 386k buffer hits) and **about 330k buffer hits** on `products_pkey`. `count(DISTINCT order_id)` forces a sort by `order_id` that **spills to disk** (`external merge Disk: 2728kB` per worker at 4MB `work_mem`). The filter keeps about **97%** of delivered orders, so no index can make this selective. Covering indexes on `orders(order_status, order_purchase_timestamp) INCLUDE (order_id)`, `order_items(order_id) INCLUDE (...)` and `products(product_id) INCLUDE (category)` gave **227 ms vs 232 ms** (full range) and 67 ms vs 62 ms (one quarter): no gain. This is the natural "an index does not save this query" case (PDF section 5), and the planned fix is the snapshot table (section 5).
- **Q4** (`04_top_sellers.sql`). It aggregates reviews over the whole table, reads and sorts `orders` twice (the CTE and the outer join), and uses merge joins with big sorts. There is a severe row misestimate (`Hash Join est=25,242,183 vs actual 48,900`). Server time is 1.4 s.
- **Q5** (`05_payments.sql`). The `payment_groups` CTE aggregates all of `order_payments` and `order_items`, and the planner makes a merge join with a sort. The estimate is `24,211,231` against an actual of `50,918`. Most of the cost is the `order_items` aggregation (about 110 ms); a payments-only version of the query runs in **about 66 ms**.
- **Q2/Q3** are dominated by the multi-table view `analytics.order_delivery_reviews`, which joins `customers` and a reviews aggregate even where the query does not need it.

### 3.3 Rewrites tried (scratch files in `scripts/lab/`, 9-rep medians)

Check **semantic equality** against the current query output (`EXCEPT` both ways) before adopting any of these.

| Variant | File | Median | Notes |
| --- | --- | --- | --- |
| Q1 sargable filter, `count(DISTINCT)` kept | (ad hoc psql) | about 243 | still over budget |
| Q1 sargable filter, pre-aggregate per order+category, then `count(*)` | `q1_r2.sql` | **213** (min 182) | still not under 200 reliably; one quarter: 62 |
| Q1 aggregate items first, join orders after | `q1_items_first.sql` | 255 | worse |
| Q1 `work_mem=64MB` on current view | (psql) | 317-370 | no help |
| Q3 without the `customers` join (use `analytics.delivered_orders` and a review aggregate) | `q3_noncust.sql` | **119** | vs 166 for the current query with the index |
| Q4 top-20 sellers first, then enrich only their orders, reviews via `LATERAL` | `q4_topn.sql` | **165** (min 153) | needs `idx_order_reviews_order` |
| Q5 `order_items` aggregate joined directly, no `payment_groups` CTE | `q5_d2.sql` | **161** | **changes semantics** (average per payment row, not per order/type/installments group) |
| Q5 single pass, same semantics as current | `q5_v3_single_pass.sql` | 258 (202 with covering indexes) | borderline |
| Q5 filter orders first, scalar subquery per order | (earlier lab file) | 582 | much worse, abandon |
| Q5 window function `sum() OVER (PARTITION BY order_id)` | (earlier lab file) | 305 | no better |
| Q5 covering indexes `order_items(order_id) INCLUDE (price, freight_value)` and `order_payments(order_id, payment_type, payment_installments) INCLUDE (payment_value)` | `index_lab.py` | current query 308 to 250, v3 255 to 202 | modest |

The "Notes" and "abandon" rows are real failed or abandoned approaches for `report.md` section 3.

## 4. What is still missing against the PDF

1. **No string-built SQL (checked strictly).** Replace these:
   - `benchmark.py`: `"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement.text`. Use a SQLAlchemy `Explain` construct with `@compiles` (the documented recipe), or static `.sql` files.
   - `loader.py`: `"TRUNCATE TABLE " + ", ".join(...)` and `f'ANALYZE olist."{name}"'`. Use static `.sql` files under `sql/` or SQLAlchemy `delete()` constructs.
   - `scripts/inspect_db.py` builds a `count(*)` statement with quoted identifiers; it is a dev helper, but do not ship it as-is.
2. **Sixth query or the "index cannot save it" query (section 5 of the PDF).** Q1 is the natural candidate (evidence in 3.2). It must end under 200 ms by a non-index route and the report must say: why the index was useless (plan evidence), what in the formulation blocked it (non-sargable view filter, about 97% selectivity), what was done (read from `analytics.monthly_category_snapshot` built by `analytics.rebuild_monthly_snapshot`), and what it costs (freshness, space, maintenance).
3. **Queries still over budget at the full range:** Q1 (213 even sargable), Q4 (967 baseline; 165 with `q4_topn`), Q5 (426; about 161-202 depending on semantics). Move the winning rewrites into `sql/queries/` and drop or rewrite the old text. Q5 option not yet measured: a per-order totals table (items value per order, rebuilt by a procedure) joined to payments.
4. **Index decisions with plan evidence.** Rewrite `003_candidate_indexes.sql` so it only contains indexes with documented plan justification. Keep `idx_order_reviews_order` (justified). Test `order_items(seller_id) INCLUDE (order_id, price)` for Q4 (`t_items_seller` is defined in `index_lab.py` but was not measured). Drop `idx_order_payments_order` (redundant with the PK) and the unused ones, each with a numbered migration and an explanation. At least one built-then-dropped index must be reported.
5. **Index hidden costs (PDF section 4).** The notebook currently compares two full loads that include Python parsing, which dilutes the signal. Measure pure bulk insert (for example `INSERT ... SELECT` of N rows into scratch tables with and without indexes, rolled back, at least 3 repetitions), per-index size and total index size relative to table size (`database_sizes()` already returns these).
6. **Python-SQL bridge in the notebook (PDF section 8):** read a large query into a DataFrame in **chunks** (`pd.read_sql(..., chunksize=...)`), write a DataFrame with an explicit `dtype=` column mapping (not defaults), and show a read from a **view**. Keep explicit connection management and call `engine.dispose()` at the end.
7. **One command from an empty PostgreSQL to a complete DB.** Add something like `nyc311-db build` that applies all migrations (including the final indexes), loads Olist, loads Stage 1 into `nyc311` through the Stage 1 package, and builds the snapshots. `load` currently does not create the final indexes.
8. **Tests.** At least 6 data-layer tests are required. 8 integration tests exist (function value, procedure idempotency, query correctness on a small controlled dataset) but they need an empty test DB (section 2). Add tests for any new query semantics, the new views, procedure failure atomicity, and the "no string-built SQL" rule.
9. **Notebook.** Re-run end to end on a fresh kernel (Restart and Run All). Cell execution counts must be 1..N, outputs saved, paths relative, one seed defined once at the top (currently 42), Markdown in Persian, code and docstrings in English, runtime under **10 minutes** excluding the initial load. Two full 1M-row geolocation loads may be too slow; measure. The notebook must document, per query, original text + time + plan, plan reading, change, time + plan after, and one sentence on why it worked.
10. **`report.md`** (Persian, 800-1500 words, every number traceable to a notebook output): the current file is a draft with no numbers. Fill it from `data/curated/performance_results.json`. It needs: problem understanding and assumptions; at least 5 decisions with alternatives, choice, numeric evidence and what was lost; failures (section 3.3 gives real ones); limits and risks; "two more days" paragraph; the Function vs Procedure explanation using your own code (`analytics.delivery_delay_days` is usable inside `SELECT`; `analytics.rebuild_monthly_snapshot` writes data, is idempotent via DELETE+INSERT under an advisory lock and rolls back atomically); FK-violation counts and handling; `AI usage` section kept accurate.
11. **Referential integrity numbers for the report.** Expected from the source: 13 products and 24 order_items rejected because 2 product categories (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) are absent from the translation table. This comes from the row counts above versus the usual Olist sizes (32,951 products, 112,650 items), **not yet confirmed**: read the loader summary or `data/curated/integrity_quarantine.jsonl`. Decide whether to keep quarantining those rows (current behaviour) or supplement the translation table, and report either choice with the revenue affected.
12. **Docs.** `README.md` and `GETTING_STARTED.md` are close to correct. Update them for the `build` command and the final index set, and fix the odd `Read-Host "1234"` prompt text. Remove or promote `scripts/lab/*`.

## 5. Recommended finishing order

1. `init-db --reset`, reload, record the true baseline plans with the unchanged queries (needed for the notebook's before/after).
2. Fix the string-built SQL in `benchmark.py` and `loader.py` (section 4, item 1).
3. Adopt rewrites: Q3 (`q3_noncust`), Q4 (`q4_topn`), Q5 (decide semantics, then `q5_d2` or totals table). Verify equality with `EXCEPT`. Q1 reads from the snapshot (build all months through the procedure first; compare view vs snapshot timing, already coded in the notebook's section 4).
4. Finalize indexes (section 4, item 4), measure write cost and sizes (item 5).
5. Add the chunked read, typed `to_sql` and view-read cells (item 6), add `build` (item 7), add tests against `olist_test`.
6. Run the notebook fresh, then write `report.md` from the saved outputs.
7. Commit in small steps (not done: suggested split: schema/loader fixes, queries, indexes and migrations, benchmark/write-cost, notebook, tests, report, docs) and open a PR.

## 6. Files added this session (dev helpers, no production code was changed)

- `scripts/with_local_db.py`: runs a command with `DATABASE_URL` built from the Docker container.
- `scripts/inspect_db.py`: lists relations and row counts.
- `scripts/quick_bench.py`: runs the 5 queries with plan nodes (`-v`).
- `scripts/lab/time_sql.py`, `scripts/lab/index_lab.py`, `scripts/lab/q*.sql`: scratch experiments from section 3.3. Move winning SQL into `sql/queries/` and delete the rest.
