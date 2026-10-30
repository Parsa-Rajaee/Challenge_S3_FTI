WITH order_values AS (
    SELECT order_id, sum(price + freight_value) AS order_value
    FROM olist.order_items GROUP BY order_id
), payment_groups AS (
    SELECT order_id, payment_type, payment_installments,
           count(*) AS payment_rows, sum(payment_value) AS paid_value
    FROM olist.order_payments
    GROUP BY order_id, payment_type, payment_installments
)
SELECT p.payment_type, p.payment_installments,
       sum(p.payment_rows) AS payment_rows, count(*) AS order_group_count,
       avg(p.paid_value) AS mean_paid_value,
       avg(v.order_value) AS mean_order_value
FROM payment_groups AS p
JOIN olist.orders AS o USING (order_id)
LEFT JOIN order_values AS v USING (order_id)
WHERE o.order_purchase_timestamp >= :start_date AND o.order_purchase_timestamp < :end_date
GROUP BY 1, 2 ORDER BY 1, 2;
