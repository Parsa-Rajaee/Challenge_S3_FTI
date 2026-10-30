-- Source timestamps are Brazilian local wall times, not timezone-qualified instants.
CREATE SCHEMA olist;
CREATE SCHEMA analytics;

CREATE TABLE olist.category_translations (
    product_category_name text PRIMARY KEY,
    product_category_name_english text NOT NULL
);
CREATE TABLE olist.customers (
    customer_id uuid PRIMARY KEY,
    customer_unique_id uuid NOT NULL,
    customer_zip_code_prefix varchar(5) NOT NULL CHECK (customer_zip_code_prefix ~ '^[0-9]{5}$'),
    customer_city text NOT NULL,
    customer_state varchar(2) NOT NULL CHECK (customer_state ~ '^[A-Z]{2}$')
);
CREATE TABLE olist.sellers (
    seller_id uuid PRIMARY KEY,
    seller_zip_code_prefix varchar(5) NOT NULL CHECK (seller_zip_code_prefix ~ '^[0-9]{5}$'),
    seller_city text NOT NULL,
    seller_state varchar(2) NOT NULL CHECK (seller_state ~ '^[A-Z]{2}$')
);
CREATE TABLE olist.products (
    product_id uuid PRIMARY KEY,
    product_category_name text REFERENCES olist.category_translations,
    product_name_length integer CHECK (product_name_length >= 0),
    product_description_length integer CHECK (product_description_length >= 0),
    product_photos_qty integer CHECK (product_photos_qty >= 0),
    product_weight_g numeric(14,3) CHECK (product_weight_g >= 0),
    product_length_cm numeric(14,3) CHECK (product_length_cm >= 0),
    product_height_cm numeric(14,3) CHECK (product_height_cm >= 0),
    product_width_cm numeric(14,3) CHECK (product_width_cm >= 0)
);
-- Olist timestamps have no timezone offset; retain their source wall-clock values.
CREATE TABLE olist.orders (
    order_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES olist.customers,
    order_status text NOT NULL CHECK (order_status IN (
        'created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered', 'unavailable', 'canceled'
    )),
    order_purchase_timestamp timestamp NOT NULL,
    order_approved_at timestamp,
    order_delivered_carrier_date timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date timestamp
);
-- Fixed-scale numerics preserve cent-valued money without binary float error.
CREATE TABLE olist.order_items (
    order_id uuid NOT NULL REFERENCES olist.orders,
    order_item_id integer NOT NULL CHECK (order_item_id > 0),
    product_id uuid NOT NULL REFERENCES olist.products,
    seller_id uuid NOT NULL REFERENCES olist.sellers,
    shipping_limit_date timestamp NOT NULL,
    price numeric(12,2) NOT NULL CHECK (price >= 0),
    freight_value numeric(12,2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);
CREATE TABLE olist.order_payments (
    order_id uuid NOT NULL REFERENCES olist.orders,
    payment_sequential integer NOT NULL CHECK (payment_sequential > 0),
    payment_type text NOT NULL CHECK (payment_type IN (
        'credit_card', 'boleto', 'voucher', 'debit_card', 'not_defined'
    )),
    payment_installments integer NOT NULL CHECK (payment_installments >= 0),
    payment_value numeric(12,2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);
-- A review_id can occur on more than one order in the source.
CREATE TABLE olist.order_reviews (
    review_id uuid NOT NULL,
    order_id uuid NOT NULL REFERENCES olist.orders,
    review_score smallint NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title text,
    review_comment_message text,
    review_creation_date timestamp NOT NULL,
    review_answer_timestamp timestamp,
    PRIMARY KEY (review_id, order_id)
);
-- ZIP prefixes are not unique in these samples; exact NUMERIC coordinates avoid rounding.
CREATE TABLE olist.geolocation (
    geolocation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    geolocation_zip_code_prefix varchar(5) NOT NULL CHECK (geolocation_zip_code_prefix ~ '^[0-9]{5}$'),
    geolocation_lat numeric NOT NULL CHECK (geolocation_lat BETWEEN -90 AND 90),
    geolocation_lng numeric NOT NULL CHECK (geolocation_lng BETWEEN -180 AND 180),
    geolocation_city text NOT NULL,
    geolocation_state varchar(2) NOT NULL CHECK (geolocation_state ~ '^[A-Z]{2}$')
);
