TRUNCATE TABLE
    olist.geolocation,
    olist.order_reviews,
    olist.order_payments,
    olist.order_items,
    olist.orders,
    olist.products,
    olist.sellers,
    olist.customers,
    olist.category_translations
RESTART IDENTITY CASCADE;
