-- ============================================================================
-- Query 01: Monthly Category Revenue & Order Metrics
-- ============================================================================
-- Business Context:
--   Calculates monthly sales performance by product category (English name),
--   including total revenue, distinct order count, and average order value (AOV).
--
-- Performance & Execution Characteristics:
--   - Underlying View: analytics.monthly_category_revenue
--   - Challenge: The view joins 4 tables (orders, order_items, products, translations)
--     and aggregates with `date_trunc('month', ...)` and `COUNT(DISTINCT order_id)`.
--   - Index Limitation: Standard B-Tree indexes on order_purchase_timestamp cannot
--     bypass the expensive join and multi-key aggregation when filtering by month.
--   - High-Performance Alternative: For recurring dashboard workloads, use the
--     pre-aggregated table `analytics.monthly_category_snapshot` (rebuilt via
--     procedure `analytics.rebuild_monthly_snapshot`), achieving sub-10ms response.
-- ============================================================================

SELECT
    month,                  -- Truncated first day of the calendar month (YYYY-MM-01)
    category,               -- English category name (fallback: Portuguese or '__uncategorized__')
    revenue,                -- Total gross revenue (sum of item prices) in BRL
    order_count,            -- Distinct delivered orders count
    average_order_value     -- revenue / order_count (Average Order Value)
FROM analytics.monthly_category_revenue
WHERE month >= :start_date  -- Filter range start (inclusive parameter)
  AND month < :end_date     -- Filter range end (exclusive parameter)
ORDER BY
    month,
    category;
