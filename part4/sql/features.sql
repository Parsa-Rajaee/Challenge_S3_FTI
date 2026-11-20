-- These input-table attributes require an explicit upstream availability contract.
-- Olist does not timestamp order-item/payment record creation.
CREATE SCHEMA IF NOT EXISTS capstone;
CREATE TABLE IF NOT EXISTS capstone.holidays (holiday_date date PRIMARY KEY,holiday_name text NOT NULL,source text NOT NULL);
DROP MATERIALIZED VIEW IF EXISTS capstone.features;
CREATE MATERIALIZED VIEW capstone.features AS
WITH item_features AS (
 SELECT i.order_id,COUNT(*)::int item_count,COUNT(DISTINCT i.seller_id)::int seller_count,
 COUNT(DISTINCT i.product_id)::int product_count,SUM(i.price)::float8 item_value,
 SUM(i.freight_value)::float8 freight_value,AVG(p.product_weight_g)::float8 mean_weight_g,
 AVG(p.product_photos_qty)::float8 mean_photos,AVG(p.product_description_length)::float8 mean_description_length,
 MAX((s.seller_state<>c.customer_state)::int)::int interstate_seller
 FROM olist.order_items i JOIN olist.orders o ON o.order_id=i.order_id
 JOIN olist.customers c ON o.customer_id=c.customer_id
 JOIN olist.sellers s ON s.seller_id=i.seller_id
 JOIN olist.products p ON p.product_id=i.product_id GROUP BY i.order_id
), payment_features AS (
 SELECT order_id,COUNT(*)::int payment_count,MAX(payment_installments)::int max_installments,
 SUM(payment_value)::float8 payment_value,MAX((payment_type='boleto')::int)::int uses_boleto,
 MAX((payment_type='voucher')::int)::int uses_voucher
 FROM olist.order_payments GROUP BY order_id
)
SELECT o.order_id,o.order_approved_at approved_at,
 EXTRACT(DOW FROM o.order_approved_at)::int approval_weekday,
 EXTRACT(MONTH FROM o.order_approved_at)::int approval_month,
 EXTRACT(HOUR FROM o.order_approved_at)::int approval_hour,
 EXTRACT(EPOCH FROM (o.order_approved_at-o.order_purchase_timestamp))/3600.0 approval_lag_hours,
 c.customer_state,LEFT(c.customer_zip_code_prefix,2) customer_zip_region,
 COALESCE(i.item_count,0) item_count,COALESCE(i.seller_count,0) seller_count,
 COALESCE(i.product_count,0) product_count,COALESCE(i.item_value,0) item_value,
 COALESCE(i.freight_value,0) freight_value,COALESCE(i.mean_weight_g,0) mean_weight_g,
 COALESCE(i.mean_photos,0) mean_photos,COALESCE(i.mean_description_length,0) mean_description_length,
 COALESCE(i.interstate_seller,0) interstate_seller,COALESCE(pay.payment_count,0) payment_count,
 COALESCE(pay.max_installments,0) max_installments,COALESCE(pay.payment_value,0) payment_value,
 COALESCE(pay.uses_boleto,0) uses_boleto,COALESCE(pay.uses_voucher,0) uses_voucher,
 (EXTRACT(ISODOW FROM o.order_approved_at) IN (6,7))::int is_weekend,
 (h.holiday_date IS NOT NULL)::int is_public_holiday
FROM olist.orders o JOIN olist.customers c ON c.customer_id=o.customer_id
LEFT JOIN item_features i ON i.order_id=o.order_id
LEFT JOIN payment_features pay ON pay.order_id=o.order_id
LEFT JOIN capstone.holidays h ON h.holiday_date=o.order_approved_at::date
WHERE o.order_approved_at IS NOT NULL;
CREATE UNIQUE INDEX capstone_features_order_id_idx ON capstone.features(order_id);
CREATE INDEX capstone_features_approved_at_idx ON capstone.features(approved_at);
ANALYZE capstone.features;
