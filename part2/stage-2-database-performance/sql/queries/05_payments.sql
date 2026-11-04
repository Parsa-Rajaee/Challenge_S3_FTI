-- ============================================================================
-- Query 05: Payment Methods, Installment Distribution, and Basket Value
-- ============================================================================
-- Business Context:
--   Analyzes payment instrument usage patterns (credit card, boleto, voucher,
--   debit card), installment adoption, total transaction counts, and compares
--   actual payment values against total order merchandise value (items + freight).
--
-- Performance & Execution Characteristics:
--   - Two-Level Hierarchical Aggregation:
--     1. Inner subquery `grouped`: Groups payments per `(order_id, payment_type,
--        payment_installments)` to collapse multi-voucher or multi-card transactions
--        at the order level without causing Cartesian fan-out against order items.
--     2. Pre-aggregated Order Value: Subquery `v` aggregates item prices + freight
--        per `order_id` in isolation before joining.
--     3. Outer query: Aggregates across all orders by `(payment_type, payment_installments)`.
--   - Index Support:
--     - `idx_order_payments_order` on `olist.order_payments (order_id)` speeds up
--       the join with orders.
--     - B-Tree index on `orders (order_purchase_timestamp)` restricts the scanned
--       cohort strictly to the designated date window.
-- ============================================================================

SELECT
    grouped.payment_type,
    grouped.payment_installments,
    sum(grouped.payment_rows) AS payment_rows,        -- Total payment transaction lines processed
    count(*) AS order_group_count,                    -- Number of unique order-payment method combinations
    avg(grouped.paid_value) AS mean_paid_value,       -- Average amount paid via this payment method/installment
    avg(grouped.order_value) AS mean_order_value      -- Average total order basket value (items + freight)

FROM (
    -- Inner rollup: Calculate order-level payment sum and total order value
    SELECT
        p.order_id,
        p.payment_type,
        p.payment_installments,
        count(*) AS payment_rows,
        sum(p.payment_value) AS paid_value,
        max(v.order_value) AS order_value
    FROM olist.order_payments AS p
    JOIN olist.orders AS o USING (order_id)
    -- Join with pre-aggregated order items to avoid multiplying payment lines with item rows
    LEFT JOIN (
        SELECT
            order_id,
            sum(price + freight_value) AS order_value
        FROM olist.order_items
        GROUP BY order_id
    ) AS v USING (order_id)
    WHERE o.order_purchase_timestamp >= :start_date
      AND o.order_purchase_timestamp < :end_date
    GROUP BY
        p.order_id,
        p.payment_type,
        p.payment_installments
) AS grouped

GROUP BY
    1, -- payment_type
    2  -- payment_installments
ORDER BY
    1, -- payment_type
    2; -- payment_installments
