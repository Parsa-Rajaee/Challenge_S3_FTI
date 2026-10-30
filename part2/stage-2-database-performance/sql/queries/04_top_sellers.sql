WITH seller_orders AS (
    SELECT i.seller_id, i.order_id, sum(i.price) AS revenue
    FROM olist.order_items AS i
    JOIN olist.orders AS o USING (order_id)
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
    GROUP BY i.seller_id, i.order_id
), reviews AS (
    SELECT order_id, avg(review_score) AS score
    FROM olist.order_reviews GROUP BY order_id
)
SELECT s.seller_id, seller.seller_city, seller.seller_state, sum(s.revenue) AS revenue,
       avg(CASE WHEN o.order_delivered_carrier_date >= o.order_approved_at
           THEN extract(epoch FROM (o.order_delivered_carrier_date - o.order_approved_at)) / 86400.0
           END) AS mean_preparation_days,
       avg(r.score) AS mean_review_score
FROM seller_orders AS s
JOIN olist.orders AS o USING (order_id)
JOIN olist.sellers AS seller USING (seller_id)
LEFT JOIN reviews AS r USING (order_id)
GROUP BY s.seller_id, seller.seller_city, seller.seller_state ORDER BY revenue DESC, s.seller_id LIMIT 20;
