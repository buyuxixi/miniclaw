-- Compatibility baseline for the 23 existing business tables; no table is renamed.
-- Existing business DDL consolidated on 2026-10-08. Additive compatibility baseline.

CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS bindings (name TEXT PRIMARY KEY, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS canvas_history (project TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(project,seq));

CREATE TABLE IF NOT EXISTS canvas_jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS canvas_plans (id TEXT PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS canvas_projects (id TEXT PRIMARY KEY, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS canvas_selections (project TEXT PRIMARY KEY, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS creation_decisions (scope TEXT, id TEXT, signature TEXT, reserve INTEGER, data TEXT, PRIMARY KEY(scope,id));

CREATE TABLE IF NOT EXISTS creator_jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS creator_projects (id TEXT PRIMARY KEY, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS image_jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS studio_image_requests (workspace TEXT, id TEXT, signature TEXT, data TEXT, PRIMARY KEY(workspace,id));

CREATE TABLE IF NOT EXISTS studio_limits (workspace TEXT PRIMARY KEY, calls INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS studio_links (workspace TEXT PRIMARY KEY, chat_id TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS studio_projects (workspace TEXT PRIMARY KEY, name TEXT NOT NULL, origin TEXT);

CREATE TABLE IF NOT EXISTS studio_reservations (workspace TEXT, job TEXT PRIMARY KEY);

CREATE TABLE IF NOT EXISTS studio_video_jobs (id TEXT PRIMARY KEY,workspace TEXT,data TEXT);

CREATE TABLE IF NOT EXISTS studio_video_renders (id TEXT PRIMARY KEY,workspace TEXT,data TEXT);

CREATE TABLE IF NOT EXISTS turns (row_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS video_precision_links
                  (workspace TEXT, object_id TEXT, data TEXT, PRIMARY KEY(workspace,object_id));

CREATE TABLE IF NOT EXISTS video_precision_requests
                  (project TEXT, request_id TEXT, signature TEXT, data TEXT,
                   PRIMARY KEY(project,request_id));

CREATE TABLE IF NOT EXISTS video_workspace_receipts (workspace TEXT, id TEXT, signature TEXT, data TEXT, PRIMARY KEY(workspace,id));

CREATE TABLE IF NOT EXISTS video_workspaces (id TEXT PRIMARY KEY, data TEXT);
