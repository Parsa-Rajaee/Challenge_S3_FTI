CREATE SCHEMA IF NOT EXISTS nyc311;
CREATE TABLE IF NOT EXISTS nyc311.service_requests (
    unique_key bigint PRIMARY KEY,
    created_date timestamptz NOT NULL,
    closed_date timestamptz,
    agency text NOT NULL,
    complaint_type text NOT NULL,
    descriptor text,
    incident_zip varchar(5) CHECK (incident_zip ~ '^[0-9]{5}$'),
    borough text CHECK (borough IS NULL OR borough IN ('BRONX', 'BROOKLYN', 'MANHATTAN', 'QUEENS', 'STATEN ISLAND')),
    closure_days double precision CHECK (closure_days >= 0),
    CHECK (closed_date IS NULL OR closed_date >= created_date)
);
