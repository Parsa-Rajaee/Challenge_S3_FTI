CREATE SCHEMA IF NOT EXISTS capstone;
DROP MATERIALIZED VIEW IF EXISTS capstone.features;
DROP VIEW IF EXISTS capstone.feature_rows;
DROP MATERIALIZED VIEW IF EXISTS capstone.shipping_days;
CREATE MATERIALIZED VIEW capstone.shipping_days AS
WITH events AS (
    SELECT order_delivered_carrier_date::date AS day, 'shipment' AS kind FROM olist.orders
    UNION ALL
    SELECT order_delivered_customer_date::date, 'delivery' FROM olist.orders
    UNION ALL
    SELECT review_answer_timestamp::date, 'reply' FROM olist.order_reviews
    UNION ALL
    SELECT review_answer_timestamp::date, 'negative' FROM olist.order_reviews WHERE review_score <= 2
)
SELECT day, count(*) FILTER (WHERE kind='shipment') AS shipments,
       count(*) FILTER (WHERE kind='delivery') AS deliveries,
       count(*) FILTER (WHERE kind='reply') AS replies,
       count(*) FILTER (WHERE kind='negative') AS negatives
FROM events WHERE day IS NOT NULL GROUP BY day;
CREATE UNIQUE INDEX ON capstone.shipping_days(day);
CREATE VIEW capstone.feature_rows AS {feature_query};
CREATE MATERIALIZED VIEW capstone.features AS SELECT * FROM capstone.feature_rows;
CREATE UNIQUE INDEX ON capstone.features(order_id);
ANALYZE capstone.features;
