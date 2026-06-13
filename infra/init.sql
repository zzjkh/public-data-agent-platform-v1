CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS reporting;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_readonly') THEN
    CREATE ROLE app_readonly LOGIN PASSWORD 'app_readonly';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA reporting TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO app_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting GRANT SELECT ON TABLES TO app_readonly;
ALTER ROLE app_readonly SET search_path = reporting;

