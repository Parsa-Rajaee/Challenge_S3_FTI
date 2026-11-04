-- ============================================================================
-- Migration 003: Candidate Performance Indexes & Write-Cost Tradeoff Candidates
-- ============================================================================
-- Design Strategy:
--   Every secondary index speeds up read queries but imposes maintenance overhead
--   on INSERT, UPDATE, and DELETE operations, while consuming shared buffer cache.
--   Here we declare targeted indexes designed for the 5 dashboard queries, plus one
--   deliberate candidate index on geolocation to evaluate and retire.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Partial Index: Delivered Orders by Purchase Timestamp
-- Benefits: Query 01, Query 02, Query 04, Query 05
-- Rationale: Only ~97% of orders are 'delivered'. A partial index reduces index
-- size and index tree depth by omitting non-delivered orders.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_orders_delivered_purchase
    ON olist.orders (order_purchase_timestamp)
    WHERE order_status = 'delivered';

-- ----------------------------------------------------------------------------
-- Foreign Key Index: Orders by Customer
-- Benefits: Query 02 (joining orders with customers to obtain state)
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_orders_customer
    ON olist.orders (customer_id);

-- ----------------------------------------------------------------------------
-- Composite Index: Order Items by Seller and Order
-- Benefits: Query 04 (identifying top sellers and mapping seller orders)
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_order_items_seller
    ON olist.order_items (seller_id, order_id);

-- ----------------------------------------------------------------------------
-- Foreign Key Index: Order Items by Product ID
-- Benefits: Query 01 (joining order_items with products)
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_order_items_product
    ON olist.order_items (product_id);

-- ----------------------------------------------------------------------------
-- Foreign Key Index: Order Payments by Order ID
-- Benefits: Query 05 (aggregating payments per order)
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_order_payments_order
    ON olist.order_payments (order_id);

-- ----------------------------------------------------------------------------
-- Covering Index (Index-Only Scan): Reviews by Order ID with Review Score
-- Benefits: Query 03 and Query 04 (LATERAL join)
-- Rationale: Including `review_score` in the leaf pages via `INCLUDE` allows
-- PostgreSQL to satisfy `avg(review_score)` entirely inside index pages without
-- visiting the heap table. In Query 04, this reduces runtime from ~85s to ~211ms!
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_order_reviews_order
    ON olist.order_reviews (order_id)
    INCLUDE (review_score);

-- ----------------------------------------------------------------------------
-- Foreign Key Index: Products by Category Name
-- Benefits: Query 01 (joining products with translations)
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_products_category
    ON olist.products (product_category_name);

-- ----------------------------------------------------------------------------
-- Write-Cost / Decoy Candidate: Geolocation ZIP Code Prefix
-- Usage: NONE of the 5 business questions query the geolocation table.
-- Rationale: This index is created deliberately to measure write overhead
-- and index bloat on a 1-million row table, and is subsequently retired in 004.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_geolocation_zip
    ON olist.geolocation (geolocation_zip_code_prefix);
