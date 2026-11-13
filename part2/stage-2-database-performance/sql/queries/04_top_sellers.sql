-- Query 04: Top 20 sellers by delivered merchandise revenue in [start_date, end_date).
-- Keep one row per seller/order for preparation time and review weighting.
-- Materialization prevents the small top-20 estimate from propagating through
-- the distinct-order/review joins. Reviews are aggregated once, not once per order.
WITH top_sellers AS MATERIALIZED (
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
), seller_orders AS MATERIALIZED (
    SELECT DISTINCT
        i.seller_id,
        i.order_id,
        o.order_approved_at,
        o.order_delivered_carrier_date
    FROM olist.order_items AS i
    JOIN top_sellers USING (seller_id)
    JOIN olist.orders AS o USING (order_id)
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= :start_date
      AND o.order_purchase_timestamp < :end_date
), order_reviews AS (
    -- Deduplicate shared orders before joining reviews, then average per order.
    SELECT r.order_id, avg(r.review_score) AS score
    FROM olist.order_reviews AS r
    JOIN (SELECT DISTINCT order_id FROM seller_orders) AS selected USING (order_id)
    GROUP BY r.order_id
), seller_metrics AS MATERIALIZED (
    SELECT
        o.seller_id,
        avg(
            CASE
                WHEN o.order_delivered_carrier_date >= o.order_approved_at
                THEN extract(epoch FROM (o.order_delivered_carrier_date - o.order_approved_at)) / 86400.0
            END
        ) AS mean_preparation_days,
        avg(review.score) AS mean_review_score
    FROM seller_orders AS o
    LEFT JOIN order_reviews AS review USING (order_id)
    GROUP BY o.seller_id
)
SELECT
    top_sellers.seller_id,
    seller.seller_city,
    seller.seller_state,
    top_sellers.revenue,
    seller_metrics.mean_preparation_days,
    seller_metrics.mean_review_score
FROM top_sellers
JOIN olist.sellers AS seller USING (seller_id)
JOIN seller_metrics USING (seller_id)
ORDER BY
    top_sellers.revenue DESC,
    top_sellers.seller_id;
