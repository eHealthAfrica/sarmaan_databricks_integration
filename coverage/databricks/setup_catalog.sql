-- One-time setup for the Coverage pipeline in a SARMAAN catalog.
--
-- The catalogs eha_ghi_sarmaan_dev / eha_ghi_sarmaan_prod and their bronze,
-- silver, gold and restricted schemas are created by the platform team, with
-- read/write for the sarmaan-engineers group. The loader creates the
-- coverage_* tables itself on its first run.
--
-- The only extra object the loader needs is the staging volume. It tries to
-- create it on its first run; if your group lacks CREATE VOLUME on the bronze
-- schema, ask an admin to run this (use eha_ghi_sarmaan_prod for production):

CREATE VOLUME IF NOT EXISTS eha_ghi_sarmaan_dev.bronze.landing
  COMMENT 'Kobo exports, mapping files, validation reports, load staging';

GRANT READ VOLUME, WRITE VOLUME ON VOLUME eha_ghi_sarmaan_dev.bronze.landing TO `sarmaan-engineers`;
