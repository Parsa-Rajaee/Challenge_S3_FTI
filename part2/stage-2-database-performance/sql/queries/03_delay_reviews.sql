SELECT CASE WHEN delay_days <= 0 THEN 'on_time'
            WHEN delay_days <= 7 THEN 'late_1_7_days'
            ELSE 'late_over_7_days' END AS delivery_bucket,
       count(*) AS reviewed_orders,
       avg(mean_review_score) AS mean_review_score
FROM analytics.order_delivery_reviews
WHERE order_purchase_timestamp >= :start_date AND order_purchase_timestamp < :end_date
  AND mean_review_score IS NOT NULL
GROUP BY 1 ORDER BY 1;
