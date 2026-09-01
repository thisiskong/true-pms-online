-- Create the role/user with a password (can log in)
CREATE ROLE pmsonline_ro WITH LOGIN PASSWORD 'pmsonline_ro';

-- Allow it to connect to the database
GRANT CONNECT ON DATABASE pmsonline TO pmsonline_ro;

\c pmsonline

-- Allow usage of the schema (adjust if you use a non-default schema)
GRANT USAGE ON SCHEMA public TO pmsonline_ro;

-- Grant SELECT on all existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO pmsonline_ro;

-- Grant SELECT on all future tables created in this schema
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO pmsonline_ro;

-- (Optional) if you also want read access to sequences, e.g. for currval()
-- GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO pmsonline_ro;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO pmsonline_ro;


-- Test connect to database
-- PGPASSWORD='pmsonline_ro' psql -h dv01 -U pmsonline_ro -d pmsonline