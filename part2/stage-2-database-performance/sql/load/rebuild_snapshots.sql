-- ============================================================================
-- Rebuild All Monthly Category Snapshots
-- ============================================================================
-- Iterates over every distinct purchase month with delivered orders and calls
-- the stored procedure `analytics.rebuild_monthly_snapshot(month)` to
-- populate the pre-aggregated table `analytics.monthly_category_snapshot`.
-- ============================================================================

DO $body$
DECLARE
    snapshot_month date;
BEGIN
    FOR snapshot_month IN
        SELECT DISTINCT date_trunc('month', order_purchase_timestamp)::date
        FROM olist.orders
        WHERE order_status = 'delivered'
        ORDER BY 1
    LOOP
        CALL analytics.rebuild_monthly_snapshot(snapshot_month);
    END LOOP;
END
$body$;
