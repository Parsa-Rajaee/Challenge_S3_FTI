-- Apply only after recorded dashboard plans confirm no question uses geolocation.
DROP INDEX IF EXISTS olist.idx_geolocation_zip;
