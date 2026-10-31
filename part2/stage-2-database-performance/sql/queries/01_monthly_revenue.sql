SELECT month, category, revenue, order_count, average_order_value
FROM analytics.monthly_category_snapshot
WHERE month >= :start_date AND month < :end_date
ORDER BY month, category;
