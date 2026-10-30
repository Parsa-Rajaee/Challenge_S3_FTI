SELECT date_trunc('month', o.order_purchase_timestamp)::date AS month, ic.category,
       sum(ic.revenue) AS revenue, count(*) AS order_count, sum(ic.revenue) / count(*) AS average_order_value
FROM (
    SELECT i.order_id, COALESCE(t.product_category_name_english, p.product_category_name, '__uncategorized__') AS category, sum(i.price) AS revenue
    FROM olist.order_items i JOIN olist.products p USING (product_id)
    LEFT JOIN olist.category_translations t USING (product_category_name)
    GROUP BY 1, 2) ic
JOIN olist.orders o USING (order_id)
WHERE o.order_status = 'delivered' AND o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
GROUP BY 1, 2 ORDER BY 1, 2;
