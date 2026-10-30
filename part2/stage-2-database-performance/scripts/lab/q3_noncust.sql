SELECT CASE WHEN delay_days <= 0 THEN 'on_time' WHEN delay_days <= 7 THEN 'late_1_7_days' ELSE 'late_over_7_days' END AS delivery_bucket,
       count(*) AS reviewed_orders, avg(mean_review_score) AS mean_review_score
FROM (SELECT analytics.delivery_delay_days(o.order_delivered_customer_date, o.order_estimated_delivery_date) AS delay_days, r.score AS mean_review_score
      FROM analytics.delivered_orders o
      JOIN (SELECT order_id, avg(review_score) AS score FROM olist.order_reviews GROUP BY order_id) r USING (order_id)
      WHERE o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date) x
GROUP BY 1 ORDER BY 1;
