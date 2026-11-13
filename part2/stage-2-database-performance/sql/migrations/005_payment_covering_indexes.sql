-- Q5 streams per-order payment/item aggregates through merge joins.
-- The recorded final plan uses all three index-only scans, avoiding heap lookups
-- and the baseline's large sort. Visibility-map maintenance is measured separately.
-- These indexes add storage and insert work; see the notebook's write experiment.
CREATE INDEX IF NOT EXISTS idx_order_payments_order_method_cover
    ON olist.order_payments (order_id, payment_type, payment_installments)
    INCLUDE (payment_value);

CREATE INDEX IF NOT EXISTS idx_order_items_order_value_cover
    ON olist.order_items (order_id) INCLUDE (price, freight_value);

CREATE INDEX IF NOT EXISTS idx_orders_order_purchase_cover
    ON olist.orders (order_id) INCLUDE (order_purchase_timestamp);
