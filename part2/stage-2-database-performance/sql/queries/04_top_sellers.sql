WITH top_sellers AS (
    SELECT i.seller_id, sum(i.price) AS revenue
    FROM olist.order_items AS i
    JOIN olist.orders AS o USING (order_id)
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= :start_date
      AND o.order_purchase_timestamp < :end_date
    GROUP BY i.seller_id
    ORDER BY revenue DESC, i.seller_id
    LIMIT 20
), seller_orders AS (
    SELECT DISTINCT top_sellers.seller_id, i.order_id
    FROM top_sellers
    JOIN olist.order_items AS i USING (seller_id)
)
SELECT top_sellers.seller_id,
       seller.seller_city,
       seller.seller_state,
       top_sellers.revenue,
       avg(
           CASE WHEN o.order_delivered_carrier_date >= o.order_approved_at
                THEN extract(epoch FROM (o.order_delivered_carrier_date - o.order_approved_at)) / 86400.0
           END
       ) AS mean_preparation_days,
       avg(review.score) AS mean_review_score
FROM top_sellers
JOIN olist.sellers AS seller USING (seller_id)
JOIN seller_orders USING (seller_id)
JOIN olist.orders AS o ON o.order_id = seller_orders.order_id
LEFT JOIN LATERAL (
    SELECT avg(review_score) AS score
    FROM olist.order_reviews
    WHERE order_id = seller_orders.order_id
) AS review ON true
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= :start_date
  AND o.order_purchase_timestamp < :end_date
GROUP BY top_sellers.seller_id, seller.seller_city, seller.seller_state, top_sellers.revenue
ORDER BY top_sellers.revenue DESC, top_sellers.seller_id;
