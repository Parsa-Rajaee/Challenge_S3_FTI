-- ============================================================================
-- Truncate All Olist Tables
-- ============================================================================
-- Drops all records across the 9 core tables before a full reload.
-- `RESTART IDENTITY` resets auto-incrementing identity columns (e.g. geolocation_id).
-- `CASCADE` ensures child tables bound by foreign keys are truncated together.
-- ============================================================================

TRUNCATE TABLE
    analytics.monthly_category_snapshot,
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
