-- ============================================================================
-- Query 04: Top 20 Sellers Performance, Fulfillment Time, and Review Ratings
-- ============================================================================
-- Business Context:
--   Identifies the top 20 marketplace sellers by delivered revenue in the target
--   window, reporting their location, revenue, dispatch turnaround (order approval
--   to carrier handover), and customer review ratings.
--
-- Performance & Execution Characteristics:
--   - Two-Phase CTE Reduction:
--     1. `top_sellers`: Isolates the top 20 sellers by aggregate revenue first,
--        dramatically pruning downstream row volumes before detailed metric joins.
--     2. `seller_orders`: Gathers distinct order IDs handled by these 20 sellers.
--   - The 400x LATERAL Join Bottleneck:
--     The `LEFT JOIN LATERAL` computes review scores per order. Without an index
--     on `olist.order_reviews (order_id)`, PostgreSQL executes a sequential scan
--     over the entire ~100,000-row reviews table for EVERY order (21,500+ scans),
--     ballooning execution time to ~85 seconds!
--   - Index Remedy:
--     With `idx_order_reviews_order ON olist.order_reviews (order_id) INCLUDE (review_score)`,
--     PostgreSQL uses an Index-Only Scan for each lateral lookup, collapsing
--     runtime from 85,379 ms down to 211 ms (a 400x speedup).
-- ============================================================================

WITH top_sellers AS (
    -- Step 1: Identify the top 20 sellers by delivered revenue in the date range
    SELECT
        i.seller_id,
        sum(i.price) AS revenue
    FROM olist.order_items AS i
    JOIN olist.orders AS o USING (order_id)
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= :start_date
      AND o.order_purchase_timestamp < :end_date
    GROUP BY i.seller_id
    ORDER BY revenue DESC, i.seller_id
    LIMIT 20
), seller_orders AS (
    -- Step 2: Extract distinct orders belonging specifically to these top 20 sellers
    SELECT DISTINCT
        top_sellers.seller_id,
        i.order_id
    FROM top_sellers
    JOIN olist.order_items AS i USING (seller_id)
)
SELECT
    top_sellers.seller_id,
    seller.seller_city,
    seller.seller_state,
    top_sellers.revenue,

    -- Mean preparation time (in days): carrier handover timestamp minus approval timestamp
    avg(
        CASE
            WHEN o.order_delivered_carrier_date >= o.order_approved_at
            THEN extract(epoch FROM (o.order_delivered_carrier_date - o.order_approved_at)) / 86400.0
        END
    ) AS mean_preparation_days,

    -- Mean customer review score for orders fulfilled by this seller
    avg(review.score) AS mean_review_score

FROM top_sellers
JOIN olist.sellers AS seller USING (seller_id)
JOIN seller_orders USING (seller_id)
JOIN olist.orders AS o ON o.order_id = seller_orders.order_id

-- Compute order review average via correlated LATERAL subquery
-- (Relies on idx_order_reviews_order for sub-millisecond per-order resolution)
LEFT JOIN LATERAL (
    SELECT avg(review_score) AS score
    FROM olist.order_reviews
    WHERE order_id = seller_orders.order_id
) AS review ON true

WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= :start_date
  AND o.order_purchase_timestamp < :end_date
GROUP BY
    top_sellers.seller_id,
    seller.seller_city,
    seller.seller_state,
    top_sellers.revenue
ORDER BY
    top_sellers.revenue DESC,
    top_sellers.seller_id;
