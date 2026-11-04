-- ============================================================================
-- Query 03: Customer Review Score Distribution Across Delivery Delay Buckets
-- ============================================================================
-- Business Context:
--   Quantifies the impact of shipping delays on customer satisfaction (NPS / CSAT).
--   Segments delivered orders into 3 delay tiers and calculates mean review score.
--
-- Performance & Execution Characteristics:
--   - Fan-out Prevention: Reviews are aggregated per `order_id` in an inline subquery
--     BEFORE joining with orders. This ensures orders with multiple reviews do not
--     falsify order counts or artificially multiply order weights.
--   - Immutable Helper: Uses `analytics.delivery_delay_days(actual, promised)`,
--     which is pure SQL, IMMUTABLE, and PARALLEL SAFE, enabling parallel query plans.
--   - Covered Indexing: Benefited by `idx_order_reviews_order` which includes
--     `review_score` as a payload column, avoiding heap lookups during review aggregation.
-- ============================================================================

SELECT
    -- Segment delivery performance into three actionable operational buckets
    CASE
        WHEN delay_days <= 0 THEN 'on_time'
        WHEN delay_days <= 7 THEN 'late_1_7_days'
        ELSE 'late_over_7_days'
    END AS delivery_bucket,

    -- Number of unique reviewed orders falling into each bucket
    count(*) AS reviewed_orders,

    -- Mean review score (1.0 to 5.0) within each bucket
    avg(mean_review_score) AS mean_review_score

FROM (
    SELECT
        -- Compute calendar delay days: actual delivery date minus estimated date
        analytics.delivery_delay_days(
            o.order_delivered_customer_date,
            o.order_estimated_delivery_date
        ) AS delay_days,
        r.score AS mean_review_score
    FROM analytics.delivered_orders AS o
    -- Join with pre-aggregated review scores to eliminate 1-to-many row multiplication
    JOIN (
        SELECT order_id, avg(review_score) AS score
        FROM olist.order_reviews
        GROUP BY order_id
    ) AS r USING (order_id)
    WHERE o.order_purchase_timestamp >= :start_date
      AND o.order_purchase_timestamp < :end_date
) AS reviewed
GROUP BY
    1  -- delivery_bucket
ORDER BY
    1; -- delivery_bucket
