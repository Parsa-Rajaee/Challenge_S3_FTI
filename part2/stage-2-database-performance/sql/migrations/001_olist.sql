-- ============================================================================
-- Migration 001: Core Olist Relational Schema Definition
-- ============================================================================
-- Architecture & Design Decisions:
--   1. Schema Namespaces:
--      - `olist`: Isolates raw transactional tables matching the upstream schema.
--      - `analytics`: Houses analytical views, helper functions, and snapshot tables.
--   2. Data Types & Precision:
--      - `UUID`: Preserves native 128-bit identifiers from the e-commerce platform.
--      - `NUMERIC(12,2)`: Used for currency (`price`, `freight_value`, `payment_value`).
--        Prevents floating-point rounding errors common to FLOAT/DOUBLE PRECISION.
--      - `NUMERIC(14,3)`: Used for physical dimensions and weights (grams, centimeters).
--      - `TIMESTAMP` (without timezone): Olist source timestamps represent Brazilian
--        local wall-clock time without UTC offsets. Storing as naive timestamp avoids
--        erroneous UTC conversions and daylight-saving shifts.
--      - Formatted strings (`varchar(5)`, `varchar(2)`): Brazilian ZIP codes (CEPs)
--        retain leading zeros; state codes are strictly two uppercase letters.
--   3. Constraints & Referential Integrity:
--      - Primary and composite foreign keys enforce referential validity across
--        customers, orders, order items, sellers, payments, and product categories.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS olist;
CREATE SCHEMA IF NOT EXISTS analytics;

-- ----------------------------------------------------------------------------
-- Category Translations: Portuguese to English dictionary
-- ----------------------------------------------------------------------------
CREATE TABLE olist.category_translations (
    product_category_name text PRIMARY KEY,
    product_category_name_english text NOT NULL
);

-- ----------------------------------------------------------------------------
-- Customers: End buyers registered on the platform
-- ----------------------------------------------------------------------------
CREATE TABLE olist.customers (
    customer_id uuid PRIMARY KEY,
    customer_unique_id uuid NOT NULL,
    customer_zip_code_prefix varchar(5) NOT NULL CHECK (customer_zip_code_prefix ~ '^[0-9]{5}$'),
    customer_city text NOT NULL,
    customer_state varchar(2) NOT NULL CHECK (customer_state ~ '^[A-Z]{2}$')
);

-- ----------------------------------------------------------------------------
-- Sellers: Merchants fulfilling marketplace orders
-- ----------------------------------------------------------------------------
CREATE TABLE olist.sellers (
    seller_id uuid PRIMARY KEY,
    seller_zip_code_prefix varchar(5) NOT NULL CHECK (seller_zip_code_prefix ~ '^[0-9]{5}$'),
    seller_city text NOT NULL,
    seller_state varchar(2) NOT NULL CHECK (seller_state ~ '^[A-Z]{2}$')
);

-- ----------------------------------------------------------------------------
-- Products: Catalog items with physical characteristics
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Orders: Order lifecycle and timestamp milestones
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Order Items: Individual line items within an order
-- Composite Key: (order_id, order_item_id)
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Order Payments: Payment tender methods, installments, and amounts
-- Composite Key: (order_id, payment_sequential)
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Order Reviews: Customer ratings and optional textual feedback
-- Composite Key: (review_id, order_id) because a single review_id can reference
-- multiple orders in the raw dataset.
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- Geolocation: Geographic coordinate lookups by ZIP code prefix
-- Surrogate Key: Auto-generated identity column because raw rows have duplicates.
-- ----------------------------------------------------------------------------
CREATE TABLE olist.geolocation (
    geolocation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    geolocation_zip_code_prefix varchar(5) NOT NULL CHECK (geolocation_zip_code_prefix ~ '^[0-9]{5}$'),
    geolocation_lat numeric NOT NULL CHECK (geolocation_lat BETWEEN -90 AND 90),
    geolocation_lng numeric NOT NULL CHECK (geolocation_lng BETWEEN -180 AND 180),
    geolocation_city text NOT NULL,
    geolocation_state varchar(2) NOT NULL CHECK (geolocation_state ~ '^[A-Z]{2}$')
);
