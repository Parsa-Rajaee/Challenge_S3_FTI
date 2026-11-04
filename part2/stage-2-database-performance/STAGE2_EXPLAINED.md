# Stage 2: Database Performance & Architecture Explained
*An End-to-End Architectural and Engineering Walkthrough for PostgreSQL E-Commerce Analytics*

---

## 1. Executive Summary & Objective

In **Stage 1**, we built a resilient extraction and curation pipeline for the NYC311 open dataset. In **Stage 2**, our focus transitions from flat-file data processing to **relational database architecture, advanced query tuning, and PostgreSQL internals**.

We take the **Brazilian E-Commerce Public Dataset by Olist** (~100,000 orders across 2016–2018) and build a production-grade analytical data warehouse in PostgreSQL 16.

### Key Engineering Challenges Solved:
1. **Relational Integrity & Validation**: Declarative schema modeling with strict check constraints, custom types, and an atomic, rollback-safe ingestion engine.
2. **The "Index Cannot Save It" Problem (Query 1)**: Recognizing when B-Tree indexing fails to optimize heavy analytical aggregations, and replacing expensive views with snapshot tables and stored procedures (**56x speedup**).
3. **The 400x Latency Catastrophe (Query 4)**: Diagnosing how a correlated `LEFT JOIN LATERAL` triggered 21,587 sequential scans (~85 seconds), and resolving it using a covering index (**211 ms**).
4. **Index Bloat & Write-Cost Tradeoffs**: Benchmarking candidate indexes against database write overhead, identifying dead indexes, and retiring an unused index to reclaim **9.17 MB** of storage.
5. **Python-SQL Integration**: Designing a memory-bounded, chunked data extraction pipeline using Pandas and SQLAlchemy.

---

## 2. Relational Schema Architecture

The database is partitioned into two distinct schema namespaces:
* **`olist`**: Houses the transactional relational tables modeling customers, orders, items, products, sellers, payments, reviews, and geolocation.
* **`analytics`**: Houses analytical views, user-defined functions (UDFs), snapshot cache tables, and maintenance stored procedures.

### Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    customers ||--o{ orders : places
    orders ||--|{ order_items : contains
    orders ||--|{ order_payments : paid_by
    orders ||--o{ order_reviews : reviewed_in
    sellers ||--o{ order_items : fulfills
    products ||--o{ order_items : ordered_as
    category_translations ||--o{ products : translates

    customers {
        uuid customer_id PK
        uuid customer_unique_id
        varchar customer_zip_code_prefix
        text customer_city
        varchar customer_state
    }

    orders {
        uuid order_id PK
        uuid customer_id FK
        text order_status
        timestamp order_purchase_timestamp
        timestamp order_approved_at
        timestamp order_delivered_carrier_date
        timestamp order_delivered_customer_date
        timestamp order_estimated_delivery_date
    }

    order_items {
        uuid order_id PK,FK
        integer order_item_id PK
        uuid product_id FK
        uuid seller_id FK
        timestamp shipping_limit_date
        numeric price
        numeric freight_value
    }

    products {
        uuid product_id PK
        text product_category_name FK
        integer product_name_length
        numeric product_weight_g
    }

    category_translations {
        text product_category_name PK
        text product_category_name_english
    }

    order_payments {
        uuid order_id PK,FK
        integer payment_sequential PK
        text payment_type
        integer payment_installments
        numeric payment_value
    }

    order_reviews {
        uuid review_id PK
        uuid order_id PK,FK
        smallint review_score
        timestamp review_creation_date
    }

    geolocation {
        bigint geolocation_id PK
        varchar geolocation_zip_code_prefix
        numeric geolocation_lat
        numeric geolocation_lng
    }
```

### Critical Data Type Decisions

| Concept | Chosen Type | Alternative Rejected | Justification |
| :--- | :--- | :--- | :--- |
| **Financial Values** | `NUMERIC(12,2)` | `FLOAT` / `DOUBLE` | Avoids IEEE 754 binary floating-point rounding errors on cents. |
| **Physical Weights** | `NUMERIC(14,3)` | `FLOAT` | Guarantees exact milligram and millimeter precision for logistics. |
| **Timestamps** | `TIMESTAMP` (naive) | `TIMESTAMPTZ` | Olist source timestamps represent Brazilian local wall-clock times without UTC offsets; forced UTC conversion creates daylight saving time errors. |
| **ZIP Codes (CEP)** | `VARCHAR(5)` | `INTEGER` | Preserves leading zeros (e.g., São Paulo ZIP prefix `01001`). Enforced with regex check `^[0-9]{5}$`. |
| **Review Primary Key**| `(review_id, order_id)`| `review_id` alone | Upstream data reveals multiple orders can share a single survey response ID. |

---

## 3. Data Ingestion & Quarantine Pipeline (`loader.py`)

The loader implements transactional reliability with in-memory referential validation:

```mermaid
flowchart TD
    A[Start: 9 Raw CSV Files] --> B[Verify Headers Against Contract]
    B --> C[Begin Single PostgreSQL Transaction]
    C --> D[TRUNCATE olist Tables CASCADE]
    D --> E[Stream CSV Rows in Batches of 2000]
    E --> F{Row Valid?}
    F -- No: Invalid Type or Broken FK --> G[Write to integrity_quarantine.jsonl]
    F -- Yes: Valid & References Exist --> H[Add to Bulk Insert Batch]
    H --> I[Execute connection.execute insert]
    G --> J[Continue Stream]
    I --> J
    J --> K[Run ANALYZE olist.*]
    K --> L[Commit Transaction]
    L --> M[Atomically Publish Quarantine File]
```

### Key Engineering Features:
1. **All-or-Nothing Transaction**: Ingestion wraps all 9 tables in `with engine.begin():`. If an unexpected database exception occurs, the entire load rolls back.
2. **In-Memory Foreign Key Checks**: Instead of waiting for database foreign key constraint errors to abort the transaction, the loader tracks valid primary keys in Python sets (`indexes[dataset.name]`). Broken foreign keys are identified in-memory and diverted to quarantine.
3. **Quarantine Audit Log**: Quarantined records are written line-by-line to `data/curated/integrity_quarantine.jsonl`. During the production load:
   - **13 products** were quarantined because their Portuguese category names (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) lacked translations in `category_translations`.
   - **24 order items** referencing those 13 quarantined products were also quarantined to preserve referential integrity.

---

## 4. The 5 Business Analytical Questions & Optimizations

### Query 1: Monthly Category Revenue & Average Order Value (AOV)
* **Question**: What are the monthly sales, distinct order counts, and AOV per product category?
* **The Naive View Bottleneck**: View `analytics.monthly_category_revenue` joins 4 tables (`orders`, `order_items`, `products`, `translations`) and groups by `date_trunc('month', ...)` with `COUNT(DISTINCT order_id)`.
  - Baseline execution takes **365.17 ms**.
  - **Why Indexes Fail**: Date truncation is non-sargable. Furthermore, 97% of all orders are delivered, meaning an index on timestamp still requires scanning almost the entire table, followed by a heavy hash join and sort.
* **The Architectural Solution**:
  We introduced a pre-aggregated snapshot table (`analytics.monthly_category_snapshot`) refreshed monthly via stored procedure `analytics.rebuild_monthly_snapshot(p_month)`.
  - **Result**: Querying the snapshot table takes **6.50 ms** — a **56x speedup**.

---

### Query 2: Late Delivery Rate by Customer State
* **Question**: What percentage of delivered orders arrived after the estimated delivery date across each Brazilian state?
* **Optimizations Applied**:
  1. **Partial Index**: `idx_orders_delivered_purchase ON olist.orders (order_purchase_timestamp) WHERE order_status = 'delivered'`. Only indexes the 97% delivered orders, keeping the B-Tree compact.
  2. **Standard SQL Filter**: `count(*) FILTER (WHERE delay_days > 0)` computes conditional counts in a single pass without cumbersome `CASE` expressions.
  - **Result**: Server execution time of **32.84 ms**.

---

### Query 3: Review Scores Across Delivery Delay Buckets
* **Question**: How do customer review ratings drop when orders are delayed by 1–7 days versus over 7 days?
* **The Fan-Out Trap & Solution**:
  If `order_reviews` is joined directly to `order_items` or `orders` before aggregation, an order with 2 reviews doubles the order count and revenue.
  - We pre-aggregate reviews in a subquery (`SELECT order_id, avg(review_score) FROM olist.order_reviews GROUP BY order_id`) before joining.
  - We use a pure SQL helper function `analytics.delivery_delay_days` marked `IMMUTABLE STRICT PARALLEL SAFE`.
  - **Result**: Execution time of **17.47 ms**.

---

### Query 4: Top 20 Sellers Fulfillment Performance & The 400x Bottleneck
* **Question**: Who are the top 20 sellers by revenue, what is their average dispatch turnaround time (approval to carrier handover), and what is their average customer review score?
* **The Latency Trap (85,379 ms)**:
  The query uses a `LEFT JOIN LATERAL` to aggregate review scores for each order belonging to the top 20 sellers.
  - **Without an index on `order_reviews.order_id`**: For all 21,587 orders handled by the top sellers, PostgreSQL executed a sequential scan over the entire ~100,000-row reviews table (**21,587 sequential scans = ~2.1 billion row inspections**), freezing the database for **85.4 seconds**!
* **The Covering Index Remedy**:
  We applied `idx_order_reviews_order ON olist.order_reviews (order_id) INCLUDE (review_score)`.
  - The planner switches to an **Index-Only Scan** using index leaf pages directly.
  - Execution time collapsed from **85,379 ms down to 211 ms** (**400x speedup**).

---

### Query 5: Payment Instruments, Installments & Basket Value
* **Question**: How do payment types and installment choices correlate with basket values?
* **Double-Aggregation Strategy**:
  Customers can pay using multiple tenders (e.g., 2 gift vouchers + 1 credit card). Joining multi-line payments to multi-line order items creates a Cartesian product.
  - We isolate order merchandise value in an independent subquery `v` (`SELECT order_id, sum(price + freight_value)`).
  - The inner aggregation groups by `(order_id, payment_type, payment_installments)` to collapse payment rows before the outer aggregation rolls up metrics.
  - **Result**: Execution time of **71.21 ms**.

---

## 5. Functions vs Stored Procedures in PostgreSQL

Understanding the distinction between User-Defined Functions (UDFs) and Stored Procedures is essential for database design:

| Characteristic | User-Defined Function (`FUNCTION`) | Stored Procedure (`PROCEDURE`) |
| :--- | :--- | :--- |
| **Invocation** | Called within expressions (`SELECT func(col) FROM tbl`) | Called standalone via `CALL proc(args)` |
| **Return Value** | Must return a value or table | Does not return values (uses `INOUT` parameters if needed) |
| **Transaction Control** | **Cannot** manage transactions (`COMMIT` or `ROLLBACK` forbidden) | **Can** commit, rollback, and manage transactions |
| **Planner Optimization** | Can be marked `IMMUTABLE`, allowing the optimizer to pre-evaluate or use in functional indexes | Evaluated dynamically at execution time |
| **Stage 2 Implementation**| `analytics.delivery_delay_days(actual, promised)` | `analytics.rebuild_monthly_snapshot(p_month)` |

### Why Advisory Locks in Procedures?
Inside `rebuild_monthly_snapshot`, we call:
```sql
PERFORM pg_advisory_xact_lock(731102, (p_month - DATE '2000-01-01')::integer);
```
- **Advisory locks** serialize concurrent batch jobs rebuilding the same month.
- `pg_advisory_xact_lock` is transaction-scoped: it releases automatically when the transaction commits or aborts, eliminating orphan lock risks.

---

## 6. The Index Write-Cost Tradeoff & Decoy Retirement

Every index is a double-edged sword:
1. **Read Benefit**: Accelerates point lookups and range scans.
2. **Write Cost**: On every `INSERT`, `UPDATE`, or `DELETE`, every secondary index must be modified, generating additional Write-Ahead Log (WAL) traffic and dirtying cache pages.
3. **Storage Overhead**: Consumes disk space and shared buffer pool memory.

### The Geolocation Index Experiment:
- In migration `003`, we deliberately created candidate index `idx_geolocation_zip` on `olist.geolocation`.
- **Finding**: None of the 5 production queries ever access the 1,000,163-row geolocation table.
- **Cost**: The index consumed **9.17 MB** (9,617,408 bytes) of storage and added significant insertion overhead during load.
- **Action**: In migration `004_drop_unused_geolocation_index.sql`, we dropped the index.
  - Total database index storage dropped from **55.90 MB to 46.73 MB**.
  - Index-to-table ratio dropped from **59.55% down to 52.79%**.

---

## 7. Python-SQL Bridge & Memory Architecture (`solution.ipynb`)

Section 5 of `solution.ipynb` demonstrates best practices when pulling large relational data into Python analytics pipelines:

1. **Memory-Bounded Chunking**:
   ```python
   CHUNK_SIZE = 20_000
   for chunk in pd.read_sql_query(query, engine, chunksize=CHUNK_SIZE):
       # Process chunk in-memory without exhausting RAM
   ```
2. **Explicit Data Type Declarations in `to_sql`**:
   Avoid letting Pandas guess SQL types as `VARCHAR` or `TEXT`. Map explicitly using SQLAlchemy types:
   ```python
   dtype = {
       "month": Date(),
       "category": Text(),
       "revenue": Numeric(12, 2),
       "order_count": Integer(),
       "average_order_value": Numeric(12, 2),
   }
   ```
3. **Connection Cleanup**: Always invoke `engine.dispose()` to close pooled connections and release PostgreSQL backend worker processes.

---

## 8. Verified Performance Benchmark Summary

All metrics are measured on PostgreSQL 16 with the full Olist dataset and recorded in `data/curated/performance_results.json`:

| Metric / Query | Baseline (No Candidate Indexes) | Optimized (With Candidate Indexes) | Snapshot Table | Speedup |
| :--- | :--- | :--- | :--- | :--- |
| **Query 1 (Monthly Revenue)** | 365.17 ms | 360.29 ms | **6.50 ms** | **56x** |
| **Query 2 (Late Deliveries)** | 42.66 ms | **32.84 ms** | N/A | 1.3x |
| **Query 3 (Delay Reviews)** | 21.05 ms | **17.47 ms** | N/A | 1.2x |
| **Query 4 (Top Sellers LATERAL)**| **85,379.28 ms** | **211.23 ms** | N/A | **404x** |
| **Query 5 (Payment Methods)** | 91.07 ms | **71.21 ms** | N/A | 1.3x |
| **Database Table Size** | 88.52 MB | 88.52 MB | 88.52 MB | - |
| **Database Index Size** | 22.04 MB (PKs only) | 55.90 MB (with candidate) | **46.73 MB** (post-004) | **-9.17 MB** |
| **Index-to-Table Ratio** | 24.89% | 59.55% | **52.79%** | - |

---

## 9. How to Verify & Run

### Run Integration & Unit Tests:
```powershell
# Set test database URL
$env:DATABASE_URL="postgresql+psycopg2://season3:1234@localhost:5432/olist_test"

# Run all Stage 2 tests
python -m unittest discover -s tests -v

# Run Stage 1 tests to ensure zero regressions
cd ../stage-1-data-pipeline
python -m unittest discover -s tests -v
```

### Inspect the Executed Jupyter Notebook:
Open `part2/stage-2-database-performance/solution.ipynb` in your IDE or JupyterLab to inspect all 7 executed cells with embedded timing outputs, execution plans, and chunked database writes.
