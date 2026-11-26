BEGIN;
CREATE TABLE IF NOT EXISTS flagguard_private.applications (
 workspace_id uuid NOT NULL REFERENCES flagguard_private.workspaces(id) ON DELETE CASCADE,
 id uuid NOT NULL, service text NOT NULL, environment text NOT NULL,
 flags text[] NOT NULL CHECK(cardinality(flags) BETWEEN 1 AND 100),
 policy jsonb NOT NULL, key_hash text NOT NULL UNIQUE,
 PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,service,environment)
);
CREATE TABLE IF NOT EXISTS flagguard_private.telemetry_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 workspace_id uuid NOT NULL, application_id uuid NOT NULL,
 payload jsonb NOT NULL, received timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(workspace_id,application_id) REFERENCES flagguard_private.applications(workspace_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tenant_events_scope ON flagguard_private.telemetry_events(workspace_id,application_id,received DESC,id DESC);
ALTER TABLE flagguard_private.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE flagguard_private.telemetry_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON flagguard_private.applications,flagguard_private.telemetry_events FROM PUBLIC,anon,authenticated;
COMMIT;
