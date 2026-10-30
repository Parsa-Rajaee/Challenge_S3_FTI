WITH win AS MATERIALIZED (
    SELECT order_id FROM olist.orders
    WHERE order_purchase_timestamp >= :start_date AND order_purchase_timestamp < :end_date
), g AS (
    SELECT p.order_id, p.payment_type, p.payment_installments, count(*) AS payment_rows, sum(p.payment_value) AS paid_value
    FROM olist.order_payments p JOIN win USING (order_id)
    GROUP BY 1, 2, 3
), v AS (
    SELECT i.order_id, sum(i.price + i.freight_value) AS order_value
    FROM olist.order_items i JOIN win USING (order_id) GROUP BY 1
)
SELECT g.payment_type, g.payment_installments, sum(g.payment_rows) AS payment_rows, count(*) AS order_group_count,
       avg(g.paid_value) AS mean_paid_value, avg(v.order_value) AS mean_order_value
FROM g LEFT JOIN v USING (order_id)
GROUP BY 1, 2 ORDER BY 1, 2;
