-- Run against a live checkout source. Dates in the historic CSV cannot replace observation time.
-- One statement sees a consistent database snapshot. Only pending approvals can acquire a new snapshot.
WITH pending AS (
    SELECT order_id, customer_id FROM olist.orders
    WHERE order_approved_at IS NULL AND order_status IN ('created', 'processing')
), basket AS (
    SELECT o.order_id, count(DISTINCT s.seller_id) AS seller_count,
           count(DISTINCT p.product_id) AS product_count,
           max((s.seller_state <> c.customer_state)::int) AS interstate_shipping
    FROM pending o
    JOIN olist.order_items i USING (order_id)
    JOIN olist.products p USING (product_id)
    JOIN olist.sellers s USING (seller_id)
    JOIN olist.customers c USING (customer_id)
    GROUP BY o.order_id
), payments AS (
    SELECT o.order_id, sum(p.payment_value) AS observed_payment_value
    FROM pending o JOIN olist.order_payments p USING (order_id)
    GROUP BY o.order_id
)
SELECT b.order_id, statement_timestamp() AT TIME ZONE 'America/Sao_Paulo' AS observed_at,
       b.seller_count, b.product_count, p.observed_payment_value, b.interstate_shipping
FROM basket b JOIN payments p USING (order_id)
ORDER BY b.order_id;
