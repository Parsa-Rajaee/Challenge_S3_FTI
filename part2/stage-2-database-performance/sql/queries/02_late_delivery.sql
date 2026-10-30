SELECT date_trunc('month', order_purchase_timestamp)::date AS month,
       customer_state, count(*) AS delivered_orders,
       count(*) FILTER (WHERE delay_days > 0) AS late_orders,
       avg((delay_days > 0)::integer) AS late_share
FROM analytics.order_delivery_reviews
WHERE order_purchase_timestamp >= :start_date AND order_purchase_timestamp < :end_date
GROUP BY 1, 2 ORDER BY 1, 2;
