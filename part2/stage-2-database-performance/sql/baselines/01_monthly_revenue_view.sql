SELECT month, category, revenue, order_count, average_order_value
FROM analytics.monthly_category_revenue
WHERE month >= :start_date AND month < :end_date
ORDER BY month, category;
