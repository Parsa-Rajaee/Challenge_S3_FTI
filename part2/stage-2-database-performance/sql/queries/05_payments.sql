-- Query 05: Payment methods/installments and basket value in [start_date, end_date).
-- Collapse payment lines before joining independently aggregated item values.
-- Covering indexes on the grouping/join keys let these live rollups stream via
-- index-only scans and merge joins, without a large intermediate sort or snapshot.
WITH grouped_payments AS (
    SELECT
        order_id,
        payment_type,
        payment_installments,
        count(*) AS payment_rows,
        sum(payment_value) AS paid_value
    FROM olist.order_payments
    GROUP BY order_id, payment_type, payment_installments
), order_values AS (
    SELECT order_id, sum(price + freight_value) AS order_value
    FROM olist.order_items
    GROUP BY order_id
), order_groups AS (
    SELECT
        p.payment_type,
        p.payment_installments,
        p.payment_rows,
        p.paid_value,
        v.order_value
    FROM grouped_payments AS p
    JOIN olist.orders AS o USING (order_id)
    -- Use the base order key's statistics, not two aggregate keys with unknown
    -- distinct counts. The LEFT JOIN preserves NULL baskets for no-item orders.
    LEFT JOIN order_values AS v ON v.order_id = o.order_id
    WHERE o.order_purchase_timestamp >= :start_date
      AND o.order_purchase_timestamp < :end_date
    -- Keep the join stream ordered before the final aggregation. This also
    -- prevents partial aggregation from duplicating the rollups across workers.
    ORDER BY p.order_id
)
SELECT
    payment_type,
    payment_installments,
    sum(payment_rows) AS payment_rows,
    count(*) AS order_group_count,
    avg(paid_value) AS mean_paid_value,
    avg(order_value) AS mean_order_value
FROM order_groups
GROUP BY payment_type, payment_installments
ORDER BY payment_type, payment_installments;
