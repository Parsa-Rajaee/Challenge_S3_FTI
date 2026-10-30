SELECT p.payment_type, p.payment_installments, count(*) AS payment_rows,
       avg(p.payment_value) AS mean_paid_value, avg(v.order_value) AS mean_order_value
FROM olist.order_payments p
JOIN olist.orders o USING (order_id)
LEFT JOIN (SELECT order_id, sum(price + freight_value) AS order_value FROM olist.order_items GROUP BY order_id) v USING (order_id)
WHERE o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
GROUP BY 1, 2 ORDER BY 1, 2;
