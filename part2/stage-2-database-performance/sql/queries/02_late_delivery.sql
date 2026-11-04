-- ============================================================================
-- Query 02: Late Delivery Rate by Customer State
-- ============================================================================
-- Business Context:
--   Monitors logistics performance and SLA compliance across Brazilian states.
--   Computes monthly delivered order volumes, late delivery counts, and late ratio.
--
-- Performance & Execution Characteristics:
--   - Underlying View: analytics.order_delivery_reviews
--   - Partial Index Support: `idx_orders_delivered_purchase` on olist.orders
--     (order_purchase_timestamp WHERE order_status = 'delivered') allows rapid
--     index range scan filtering directly to the date interval.
--   - Join Optimization: Joins orders with customers on customer_id to extract
--     customer_state. Supported by `idx_orders_customer`.
--   - Modern SQL Syntax: Uses `FILTER (WHERE ...)` rather than cumbersome CASE
--     statements for selective count aggregation.
-- ============================================================================

SELECT
    -- Truncate order timestamp to the first day of the purchase month
    date_trunc('month', order_purchase_timestamp)::date AS month,

    -- 2-letter Brazilian state code (e.g., 'SP', 'RJ', 'MG')
    customer_state,

    -- Total delivered orders in this month and state
    count(*) AS delivered_orders,

    -- Orders where actual delivery occurred after the estimated promise date
    count(*) FILTER (WHERE delay_days > 0) AS late_orders,

    -- Fraction of late deliveries: (delay_days > 0) cast to integer (0 or 1) averaged
    avg((delay_days > 0)::integer) AS late_share

FROM analytics.order_delivery_reviews
WHERE order_purchase_timestamp >= :start_date  -- Bound parameter: start timestamp
  AND order_purchase_timestamp < :end_date    -- Bound parameter: end timestamp
GROUP BY
    1, -- month
    2  -- customer_state
ORDER BY
    1, -- month
    2; -- customer_state
