WITH top_sellers AS (
    SELECT i.seller_id, sum(i.price) AS revenue
    FROM olist.order_items i JOIN olist.orders o USING (order_id)
    WHERE o.order_status = 'delivered' AND o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
    GROUP BY i.seller_id ORDER BY revenue DESC, i.seller_id LIMIT 20
), seller_orders AS (
    SELECT DISTINCT t.seller_id, i.order_id
    FROM top_sellers t JOIN olist.order_items i USING (seller_id)
)
SELECT t.seller_id, s.seller_city, s.seller_state, t.revenue,
       avg(CASE WHEN o.order_delivered_carrier_date >= o.order_approved_at
           THEN extract(epoch FROM (o.order_delivered_carrier_date - o.order_approved_at)) / 86400.0 END) AS mean_preparation_days,
       avg(r.score) AS mean_review_score
FROM top_sellers t
JOIN olist.sellers s USING (seller_id)
JOIN seller_orders so USING (seller_id)
JOIN olist.orders o ON o.order_id = so.order_id
LEFT JOIN LATERAL (SELECT avg(review_score) AS score FROM olist.order_reviews WHERE order_id = so.order_id) r ON true
WHERE o.order_status = 'delivered' AND o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
GROUP BY t.seller_id, s.seller_city, s.seller_state, t.revenue ORDER BY t.revenue DESC, t.seller_id;
