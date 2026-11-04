-- ============================================================================
-- Migration 004: Retirement of Unused Geolocation Index
-- ============================================================================
-- Operational Rationale:
--   During database profiling across all 5 production dashboard queries, execution
--   plans confirmed that `olist.geolocation` was never queried.
--   Retaining `idx_geolocation_zip` on a 1,000,163-row table consumed:
--     - 9.17 MB (9,617,408 bytes) of physical disk storage
--     - Significant write overhead during CSV bulk load / inserts
--     - Unnecessary buffer pool memory allocation
--   Dropping this index reclaims ~9.2 MB immediately and lowers the overall
--   database index-to-table size ratio from 59.55% down to 52.79%.
-- ============================================================================

DROP INDEX IF EXISTS olist.idx_geolocation_zip;
