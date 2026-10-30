SELECT month, category, sum(revenue) AS revenue, count(*) AS order_count, sum(revenue) / count(*) AS average_order_value
FROM (
    SELECT o.order_id, date_trunc('month', o.order_purchase_timestamp)::date AS month,
           COALESCE(t.product_category_name_english, p.product_category_name, '__uncategorized__') AS category,
           sum(i.price) AS revenue
    FROM olist.orders o JOIN olist.order_items i USING (order_id) JOIN olist.products p USING (product_id)
    LEFT JOIN olist.category_translations t USING (product_category_name)
    WHERE o.order_status = 'delivered' AND o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
    GROUP BY 1, 2, 3) x
GROUP BY 1, 2 ORDER BY 1, 2;
