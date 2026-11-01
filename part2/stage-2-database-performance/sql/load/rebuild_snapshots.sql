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
