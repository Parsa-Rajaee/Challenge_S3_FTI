CREATE FUNCTION analytics.delivery_delay_days(actual timestamp, promised timestamp)
RETURNS integer
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$ SELECT actual::date - promised::date $$;

CREATE VIEW analytics.delivered_orders AS
SELECT * FROM olist.orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL;

-- Aggregate reviews before joining so multiple reviews never multiply item revenue.
CREATE VIEW analytics.order_delivery_reviews AS
SELECT o.*, c.customer_state,
       analytics.delivery_delay_days(
           o.order_delivered_customer_date, o.order_estimated_delivery_date
       ) AS delay_days,
       r.mean_review_score
FROM analytics.delivered_orders AS o
JOIN olist.customers AS c USING (customer_id)
LEFT JOIN (
    SELECT order_id, avg(review_score) AS mean_review_score
    FROM olist.order_reviews GROUP BY order_id
) AS r USING (order_id);

CREATE VIEW analytics.monthly_category_revenue AS
SELECT date_trunc('month', o.order_purchase_timestamp)::date AS month,
       COALESCE(t.product_category_name_english, p.product_category_name, '__uncategorized__') AS category,
       sum(i.price) AS revenue,
       count(DISTINCT o.order_id) AS order_count,
       sum(i.price) / count(DISTINCT o.order_id) AS average_order_value
FROM olist.orders AS o
JOIN olist.order_items AS i USING (order_id)
JOIN olist.products AS p USING (product_id)
LEFT JOIN olist.category_translations AS t USING (product_category_name)
WHERE o.order_status = 'delivered'
GROUP BY 1, 2;

CREATE TABLE analytics.monthly_category_snapshot (
    month date NOT NULL CHECK (extract(day FROM month) = 1),
    category text NOT NULL,
    revenue numeric NOT NULL,
    order_count bigint NOT NULL CHECK (order_count > 0),
    average_order_value numeric NOT NULL,
    PRIMARY KEY (month, category)
);

CREATE PROCEDURE analytics.rebuild_monthly_snapshot(p_month date)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_month IS NULL OR extract(day FROM p_month) <> 1 THEN
        RAISE EXCEPTION 'p_month must be the first day of a month';
    END IF;
    -- Same-month rebuilds serialize; DELETE and INSERT roll back together on failure.
    PERFORM pg_advisory_xact_lock(731102, (p_month - DATE '2000-01-01')::integer);
    DELETE FROM analytics.monthly_category_snapshot WHERE month = p_month;
    INSERT INTO analytics.monthly_category_snapshot
        (month, category, revenue, order_count, average_order_value)
    SELECT month, category, revenue, order_count, average_order_value
    FROM analytics.monthly_category_revenue WHERE month = p_month;
END;
$$;
