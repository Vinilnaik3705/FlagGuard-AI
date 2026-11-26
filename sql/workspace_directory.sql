-- Phase 1: private workspace directory. Run with the database owner.
BEGIN;
CREATE SCHEMA IF NOT EXISTS flagguard_private;
REVOKE ALL ON SCHEMA flagguard_private FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS flagguard_private.workspaces (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS flagguard_private.members (
    workspace_id uuid NOT NULL REFERENCES flagguard_private.workspaces(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('owner','admin','viewer')),
    PRIMARY KEY(workspace_id,user_id)
);
CREATE INDEX IF NOT EXISTS members_user_idx ON flagguard_private.members(user_id);
ALTER TABLE flagguard_private.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE flagguard_private.members ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA flagguard_private FROM PUBLIC, anon, authenticated;
-- No direct browser/Data API access. Backend owner connection is privileged;
-- application queries must explicitly filter membership on every read.
COMMIT;
