SELECT o.order_id, o.order_approved_at AS approved_at,
    extract(dow from o.order_approved_at)::int AS approval_weekday,
    extract(month from o.order_approved_at)::int AS approval_month,
    extract(hour from o.order_approved_at)::int AS approval_hour,
    extract(epoch from o.order_approved_at-o.order_purchase_timestamp)/3600 AS approval_lag_hours,
    extract(hour from o.order_purchase_timestamp)::int AS purchase_hour,
    extract(dow from o.order_purchase_timestamp)::int AS purchase_weekday,
    (extract(isodow from o.order_approved_at) >= 6)::int AS is_weekend,
    (h.holiday_date IS NOT NULL)::int AS is_public_holiday,
    coalesce(c.customer_state,'UNKNOWN') AS customer_state,
    coalesce(left(c.customer_zip_code_prefix,2),'UNKNOWN') AS customer_zip_region,
    coalesce(d.shipments,0) AS prior_day_shipments,
    coalesce(d.deliveries,0) AS prior_day_deliveries,
    coalesce(d.replies,0) AS prior_day_replies,
    coalesce(d.negatives,0) AS prior_day_negatives,
    (snap.observed_at IS NOT NULL)::int AS snapshot_available,
    coalesce(snap.seller_count,0) AS seller_count,
    coalesce(snap.product_count,0) AS product_count,
    coalesce(snap.observed_payment_value,0) AS observed_payment_value,
    coalesce(snap.interstate_shipping,0) AS interstate_shipping
FROM {orders} o
LEFT JOIN olist.customers c USING (customer_id)
LEFT JOIN capstone.holidays h ON h.holiday_date = o.order_approved_at::date
LEFT JOIN capstone.shipping_days d ON d.day = o.order_approved_at::date - 1
LEFT JOIN (
    SELECT checkout_snapshots.*,
           lead(observed_at) OVER (PARTITION BY order_id ORDER BY observed_at) AS next_observation
    FROM capstone.checkout_snapshots
) snap ON snap.order_id = o.order_id
      AND snap.observed_at <= o.order_approved_at
      AND (snap.next_observation IS NULL OR o.order_approved_at < snap.next_observation)
WHERE o.order_approved_at IS NOT NULL
