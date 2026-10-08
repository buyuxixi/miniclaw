-- Actual local schema after migrations 1, 1001 and 2. Reference only.
CREATE TABLE "attachments" (id TEXT NOT NULL PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE "bindings" (name TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE "canvas_history" (project TEXT NOT NULL, seq INTEGER NOT NULL CHECK(seq>=0), data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(project,seq), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "canvas_jobs" (id TEXT NOT NULL PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "canvas_plans" (id TEXT NOT NULL PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "canvas_projects" (id TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE "canvas_selections" (project TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "creation_decisions" (scope TEXT NOT NULL, id TEXT NOT NULL, signature TEXT NOT NULL, reserve INTEGER NOT NULL CHECK(reserve>=0), data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(scope,id));

CREATE TABLE "creator_jobs" (id TEXT NOT NULL PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES creator_projects(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "creator_projects" (id TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE "file_objects" (
    id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=64 AND id NOT GLOB '*[^0-9a-f]*' AND id=sha256), backend TEXT NOT NULL,
    storage_key TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    bytes INTEGER NOT NULL CHECK(bytes>0), mime TEXT NOT NULL, created_at REAL NOT NULL,
    UNIQUE(backend,storage_key)
);

CREATE TABLE "image_jobs" (id TEXT NOT NULL PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE "media_grants" (
    scope TEXT NOT NULL, object_id TEXT NOT NULL REFERENCES file_objects(id),
    PRIMARY KEY(scope,object_id)
);

CREATE TABLE "media_heads" (
    item_id TEXT NOT NULL PRIMARY KEY REFERENCES media_items(id), revision_id TEXT NOT NULL
, FOREIGN KEY(item_id,revision_id) REFERENCES media_revisions(item_id,id));

CREATE TABLE "media_items" (
    id TEXT NOT NULL PRIMARY KEY, scope TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL,
    UNIQUE(scope,target,kind)
);

CREATE TABLE "media_revision_objects" (
    revision_id TEXT NOT NULL REFERENCES media_revisions(id), object_id TEXT NOT NULL REFERENCES file_objects(id),
    PRIMARY KEY(revision_id,object_id)
);

CREATE TABLE "media_revisions" (
    id TEXT NOT NULL PRIMARY KEY, item_id TEXT NOT NULL REFERENCES media_items(id),
    parent_id TEXT CHECK(parent_id IS NULL OR parent_id<>id), content_hash TEXT NOT NULL CHECK(length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
    data TEXT NOT NULL CHECK(json_valid(data)), label TEXT NOT NULL, created_at REAL NOT NULL
, UNIQUE(item_id,id), FOREIGN KEY(item_id,parent_id) REFERENCES media_revisions(item_id,id));

CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL);

CREATE TABLE "studio_image_requests" (workspace TEXT NOT NULL, id TEXT NOT NULL, signature TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(workspace,id), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "studio_limits" (workspace TEXT NOT NULL PRIMARY KEY, calls INTEGER NOT NULL CHECK(calls>=0));

CREATE TABLE "studio_links" (workspace TEXT NOT NULL PRIMARY KEY, chat_id TEXT NOT NULL, FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "studio_projects" (workspace TEXT NOT NULL PRIMARY KEY, name TEXT NOT NULL, origin TEXT CHECK(origin IS NULL OR json_valid(origin)), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "studio_reservations" (workspace TEXT NOT NULL, job TEXT NOT NULL PRIMARY KEY);

CREATE TABLE "studio_video_jobs" (id TEXT NOT NULL PRIMARY KEY,workspace TEXT NOT NULL,data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "studio_video_renders" (id TEXT NOT NULL PRIMARY KEY,workspace TEXT NOT NULL,data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "turns" (row_id INTEGER NOT NULL PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE "video_precision_links"
                  (workspace TEXT NOT NULL, object_id TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), project_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.project')) STORED NOT NULL REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY(workspace,object_id));

CREATE TABLE "video_precision_requests"
                  (project TEXT NOT NULL, request_id TEXT NOT NULL, signature TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)),
                   PRIMARY KEY(project,request_id), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "video_workspace_receipts" (workspace TEXT NOT NULL, id TEXT NOT NULL, signature TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(workspace,id), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "video_workspaces" (id TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

CREATE TABLE workspace_catalog (
    workspace TEXT PRIMARY KEY NOT NULL REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED,
    name TEXT NOT NULL, updated_at REAL NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
    cover TEXT, plan TEXT NOT NULL, notes INTEGER NOT NULL CHECK(notes>=0),
    pictures INTEGER NOT NULL CHECK(pictures>=0), shots INTEGER NOT NULL CHECK(shots>=0),
    adopted INTEGER NOT NULL CHECK(adopted>=0)
);

CREATE TABLE "workspace_snapshots" (
    id TEXT NOT NULL PRIMARY KEY, workspace TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
    data TEXT NOT NULL CHECK(json_valid(data)), created_at REAL NOT NULL
, FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

CREATE INDEX attachments_owner ON attachments(owner);

CREATE INDEX canvas_jobs_project ON canvas_jobs(project);

CREATE INDEX canvas_plans_project ON canvas_plans(project);

CREATE INDEX creator_jobs_project ON creator_jobs(project);

CREATE INDEX image_jobs_owner ON image_jobs(owner);

CREATE INDEX media_grants_object ON media_grants(object_id);

CREATE INDEX media_revision_objects_object ON media_revision_objects(object_id);

CREATE INDEX media_revisions_item_file ON media_revisions(item_id,json_extract(data,'$.file'));

CREATE INDEX media_revisions_item_time ON media_revisions(item_id,created_at);

CREATE INDEX studio_links_chat ON studio_links(chat_id,workspace);

CREATE INDEX studio_reservations_workspace ON studio_reservations(workspace);

CREATE INDEX studio_video_jobs_workspace ON studio_video_jobs(workspace);

CREATE INDEX studio_video_renders_workspace ON studio_video_renders(workspace);

CREATE INDEX turns_owner ON turns(owner);

CREATE INDEX video_precision_project ON video_precision_links(json_extract(data,'$.project'));

CREATE INDEX workspace_catalog_updated ON workspace_catalog(updated_at DESC,workspace);

CREATE INDEX workspace_snapshots_workspace_revision ON workspace_snapshots(workspace,revision);

CREATE TRIGGER catalog_studio_projects_insert AFTER INSERT ON studio_projects BEGIN
            INSERT OR REPLACE INTO workspace_catalog SELECT w.id,coalesce(nullif(p.name,''),nullif(json_extract(w.data,'$.state.notes[0].title'),''),nullif(json_extract(w.data,'$.state.shots[0].name'),''),'未命名画布'),
    coalesce(json_extract(w.data,'$.updated_at'),0),json_extract(w.data,'$.revision'),
    (SELECT json_extract(a.value,'$.file') FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL LIMIT 1),
    substr(coalesce(json_extract(w.data,'$.state.notes[0].text'),''),1,220),
    coalesce(json_array_length(w.data,'$.state.notes'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL),
    coalesce(json_array_length(w.data,'$.state.shots'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.sequence') a WHERE a.type='object' AND json_extract(a.value,'$.job') IS NOT NULL)
    FROM video_workspaces w LEFT JOIN studio_projects p ON p.workspace=w.id WHERE w.id=NEW.workspace; END;

CREATE TRIGGER catalog_studio_projects_update AFTER UPDATE ON studio_projects BEGIN
            INSERT OR REPLACE INTO workspace_catalog SELECT w.id,coalesce(nullif(p.name,''),nullif(json_extract(w.data,'$.state.notes[0].title'),''),nullif(json_extract(w.data,'$.state.shots[0].name'),''),'未命名画布'),
    coalesce(json_extract(w.data,'$.updated_at'),0),json_extract(w.data,'$.revision'),
    (SELECT json_extract(a.value,'$.file') FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL LIMIT 1),
    substr(coalesce(json_extract(w.data,'$.state.notes[0].text'),''),1,220),
    coalesce(json_array_length(w.data,'$.state.notes'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL),
    coalesce(json_array_length(w.data,'$.state.shots'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.sequence') a WHERE a.type='object' AND json_extract(a.value,'$.job') IS NOT NULL)
    FROM video_workspaces w LEFT JOIN studio_projects p ON p.workspace=w.id WHERE w.id=NEW.workspace; END;

CREATE TRIGGER catalog_video_workspaces_insert AFTER INSERT ON video_workspaces BEGIN
            INSERT OR REPLACE INTO workspace_catalog SELECT w.id,coalesce(nullif(p.name,''),nullif(json_extract(w.data,'$.state.notes[0].title'),''),nullif(json_extract(w.data,'$.state.shots[0].name'),''),'未命名画布'),
    coalesce(json_extract(w.data,'$.updated_at'),0),json_extract(w.data,'$.revision'),
    (SELECT json_extract(a.value,'$.file') FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL LIMIT 1),
    substr(coalesce(json_extract(w.data,'$.state.notes[0].text'),''),1,220),
    coalesce(json_array_length(w.data,'$.state.notes'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL),
    coalesce(json_array_length(w.data,'$.state.shots'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.sequence') a WHERE a.type='object' AND json_extract(a.value,'$.job') IS NOT NULL)
    FROM video_workspaces w LEFT JOIN studio_projects p ON p.workspace=w.id WHERE w.id=NEW.id; END;

CREATE TRIGGER catalog_video_workspaces_update AFTER UPDATE ON video_workspaces BEGIN
            INSERT OR REPLACE INTO workspace_catalog SELECT w.id,coalesce(nullif(p.name,''),nullif(json_extract(w.data,'$.state.notes[0].title'),''),nullif(json_extract(w.data,'$.state.shots[0].name'),''),'未命名画布'),
    coalesce(json_extract(w.data,'$.updated_at'),0),json_extract(w.data,'$.revision'),
    (SELECT json_extract(a.value,'$.file') FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL LIMIT 1),
    substr(coalesce(json_extract(w.data,'$.state.notes[0].text'),''),1,220),
    coalesce(json_array_length(w.data,'$.state.notes'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL),
    coalesce(json_array_length(w.data,'$.state.shots'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.sequence') a WHERE a.type='object' AND json_extract(a.value,'$.job') IS NOT NULL)
    FROM video_workspaces w LEFT JOIN studio_projects p ON p.workspace=w.id WHERE w.id=NEW.id; END;

CREATE TRIGGER protect_media_revision_delete BEFORE DELETE ON media_revisions BEGIN
    SELECT RAISE(ABORT,'content versions must be retained'); END;

CREATE TRIGGER protect_media_revision_update BEFORE UPDATE ON media_revisions BEGIN
    SELECT RAISE(ABORT,'content versions are immutable'); END;
