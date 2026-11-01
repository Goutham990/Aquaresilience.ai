CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Operational corridor records are supplied by real authorized operators; NO seed data.
CREATE TABLE IF NOT EXISTS marine_corridors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_node text NOT NULL,
  to_node text NOT NULL,
  geom geometry(LineString,4326) NOT NULL,
  source_id text NOT NULL,
  approved_by text NOT NULL,
  attested_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
  CHECK (ST_NPoints(geom) >= 2),
  CHECK (valid_until > attested_at),
  UNIQUE (from_node, to_node, source_id)
);
CREATE INDEX IF NOT EXISTS marine_corridors_geom_idx ON marine_corridors USING GIST (geom);

CREATE TABLE IF NOT EXISTS inventory (
  depot_id text NOT NULL,
  sku text NOT NULL,
  available_units bigint NOT NULL CHECK (available_units >= 0),
  source_id text NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (depot_id,sku)
);
CREATE TABLE IF NOT EXISTS dispatch_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key text UNIQUE NOT NULL,
  depot_id text NOT NULL,
  sku text NOT NULL,
  units bigint NOT NULL CHECK (units > 0),
  operator_id text NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS plan_audit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluated_at timestamptz NOT NULL DEFAULT now(),
  mission jsonb NOT NULL,
  plan jsonb NOT NULL
);
