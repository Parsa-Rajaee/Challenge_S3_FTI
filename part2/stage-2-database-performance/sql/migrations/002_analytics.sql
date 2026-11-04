-- ============================================================================
-- Migration 002: Analytical Views, Helper Functions, and Snapshot Stored Procedure
-- ============================================================================
-- Architecture & Design Decisions:
--   1. Functions vs Stored Procedures:
--      - `delivery_delay_days`: A pure SQL user-defined FUNCTION. It is marked
--        `IMMUTABLE` (deterministic output for given inputs, inlinable by the planner),
--        `STRICT` (returns NULL immediately if any argument is NULL), and
--        `PARALLEL SAFE` (safe for parallel query execution workers).
--      - `rebuild_monthly_snapshot`: A PL/pgSQL stored PROCEDURE. Procedures are
--        designed for transactional maintenance operations (DML side effects).
--        It uses PostgreSQL transaction-level advisory locks (`pg_advisory_xact_lock`)
--        to prevent concurrent rebuild race conditions for the same calendar month.
--   2. Views & Fan-Out Prevention:
--      - `order_delivery_reviews`: Reviews are aggregated per `order_id` in a subquery
--        BEFORE joining to orders. If joined directly, an order with 2 reviews would
--        double the item revenues and order counts in downstream aggregations.
--   3. Materialization / Snapshot Pattern:
--      - View `monthly_category_revenue` does a 4-table join and distinct aggregation (~365 ms).
--      - Table `monthly_category_snapshot` caches the calculated monthly numbers (~6.5 ms read).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Pure SQL Immutable Helper Function: Calendar Delivery Delay Calculation
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.delivery_delay_days(actual timestamp, promised timestamp)
RETURNS integer
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
    -- Subtract dates directly to compute integer calendar day difference
    SELECT actual::date - promised::date
$$;

-- ----------------------------------------------------------------------------
-- Base Analytical View: Delivered Orders with Non-Null Delivery Timestamps
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.delivered_orders AS
SELECT *
FROM olist.orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Enriched View: Delivered Orders with Customer State, Delays, and Review Scores
-- ----------------------------------------------------------------------------
-- Fan-out Protection: Aggregate reviews before joining so multiple reviews
-- never duplicate customer orders or multiply freight/revenue totals.
CREATE OR REPLACE VIEW analytics.order_delivery_reviews AS
SELECT
    o.*,
    c.customer_state,
    analytics.delivery_delay_days(
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date
    ) AS delay_days,
    r.mean_review_score
FROM analytics.delivered_orders AS o
JOIN olist.customers AS c USING (customer_id)
LEFT JOIN (
    SELECT order_id, avg(review_score) AS mean_review_score
    FROM olist.order_reviews
    GROUP BY order_id
) AS r USING (order_id);

-- ----------------------------------------------------------------------------
-- Comprehensive View: Monthly Category Revenue & Order Metrics
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.monthly_category_revenue AS
SELECT
    date_trunc('month', o.order_purchase_timestamp)::date AS month,
    -- Prefer English translation, fall back to Portuguese name, or uncategorized
    COALESCE(t.product_category_name_english, p.product_category_name, '__uncategorized__') AS category,
    sum(i.price) AS revenue,
    count(DISTINCT o.order_id) AS order_count,
    sum(i.price) / count(DISTINCT o.order_id) AS average_order_value
FROM olist.orders AS o
JOIN olist.order_items AS i USING (order_id)
JOIN olist.products AS p USING (product_id)
LEFT JOIN olist.category_translations AS t USING (product_category_name)
WHERE o.order_status = 'delivered'
GROUP BY 1, 2;

-- ----------------------------------------------------------------------------
-- Snapshot Cache Table: Pre-computed Monthly Metrics for Fast Dashboard Serving
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.monthly_category_snapshot (
    month date NOT NULL CHECK (extract(day FROM month) = 1),
    category text NOT NULL,
    revenue numeric NOT NULL,
    order_count bigint NOT NULL CHECK (order_count > 0),
    average_order_value numeric NOT NULL,
    PRIMARY KEY (month, category)
);

-- ----------------------------------------------------------------------------
-- Stored Procedure: Atomic Snapshot Rebuild for a Specified Calendar Month
-- ----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE analytics.rebuild_monthly_snapshot(p_month date)
LANGUAGE plpgsql
AS $$
BEGIN
    -- Validation: Ensure input parameter is strictly the 1st of the month
    IF p_month IS NULL OR extract(day FROM p_month) <> 1 THEN
        RAISE EXCEPTION 'p_month must be the first day of a month (YYYY-MM-01)';
    END IF;

    -- Concurrency Protection:
    -- Acquire a transaction-scoped advisory lock keyed to (731102, day_offset).
    -- If two processes attempt to rebuild the exact same month concurrently,
    -- the second process will wait until the first transaction commits or rolls back.
    PERFORM pg_advisory_xact_lock(731102, (p_month - DATE '2000-01-01')::integer);

    -- Atomic Replacement: Delete old snapshot rows and insert freshly calculated data
    DELETE FROM analytics.monthly_category_snapshot WHERE month = p_month;

    INSERT INTO analytics.monthly_category_snapshot
        (month, category, revenue, order_count, average_order_value)
    SELECT
        month,
        category,
        revenue,
        order_count,
        average_order_value
    FROM analytics.monthly_category_revenue
    WHERE month = p_month;
END;
$$;
