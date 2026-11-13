-- The full-range dashboard plans do not use these candidate indexes.
-- The narrow-date partial index keeps nearly the whole delivered cohort; the
-- customer/product indexes cannot avoid broad aggregates. The payment index is
-- covered by both the PK and migration 005's more useful covering index.
-- Keep idx_order_items_seller and idx_order_reviews_order: Q4/Q3 plans use them.
-- The notebook checks plan names before applying this retirement migration.
DROP INDEX IF EXISTS olist.idx_orders_delivered_purchase;
DROP INDEX IF EXISTS olist.idx_orders_customer;
DROP INDEX IF EXISTS olist.idx_order_items_product;
DROP INDEX IF EXISTS olist.idx_order_payments_order;
DROP INDEX IF EXISTS olist.idx_products_category;
