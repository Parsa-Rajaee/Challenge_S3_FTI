-- Candidate dashboard indexes. Compare plans and write cost before retaining these.
CREATE INDEX idx_orders_delivered_purchase
    ON olist.orders (order_purchase_timestamp)
    WHERE order_status = 'delivered';
CREATE INDEX idx_orders_customer ON olist.orders (customer_id);
CREATE INDEX idx_order_items_seller ON olist.order_items (seller_id, order_id);
CREATE INDEX idx_order_items_product ON olist.order_items (product_id);
CREATE INDEX idx_order_payments_order ON olist.order_payments (order_id);
CREATE INDEX idx_order_reviews_order ON olist.order_reviews (order_id) INCLUDE (review_score);
CREATE INDEX idx_products_category ON olist.products (product_category_name);
-- Deliberate write-cost candidate: none of the five questions reads geolocation.
CREATE INDEX idx_geolocation_zip ON olist.geolocation (geolocation_zip_code_prefix);
