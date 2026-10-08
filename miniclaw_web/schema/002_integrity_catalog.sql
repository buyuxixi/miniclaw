-- Atomic hardening migration. Column order remains compatible with legacy writers.

-- Deferred project foreign keys allow existing INSERT OR REPLACE saves without deleting history.

CREATE TABLE attachments_v2 (id TEXT NOT NULL PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO attachments_v2 (id,owner,data) SELECT id,owner,data FROM attachments;

DROP TABLE attachments;

ALTER TABLE attachments_v2 RENAME TO attachments;

CREATE TABLE bindings_v2 (name TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO bindings_v2 (name,data) SELECT name,data FROM bindings;

DROP TABLE bindings;

ALTER TABLE bindings_v2 RENAME TO bindings;

CREATE TABLE canvas_history_v2 (project TEXT NOT NULL, seq INTEGER NOT NULL CHECK(seq>=0), data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(project,seq), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO canvas_history_v2 (project,seq,data) SELECT project,seq,data FROM canvas_history;

DROP TABLE canvas_history;

ALTER TABLE canvas_history_v2 RENAME TO canvas_history;

CREATE TABLE canvas_jobs_v2 (id TEXT NOT NULL PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO canvas_jobs_v2 (id,project,data) SELECT id,project,data FROM canvas_jobs;

DROP TABLE canvas_jobs;

ALTER TABLE canvas_jobs_v2 RENAME TO canvas_jobs;

CREATE TABLE canvas_plans_v2 (id TEXT NOT NULL PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO canvas_plans_v2 (id,project,data) SELECT id,project,data FROM canvas_plans;

DROP TABLE canvas_plans;

ALTER TABLE canvas_plans_v2 RENAME TO canvas_plans;

CREATE TABLE canvas_projects_v2 (id TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO canvas_projects_v2 (id,data) SELECT id,data FROM canvas_projects;

DROP TABLE canvas_projects;

ALTER TABLE canvas_projects_v2 RENAME TO canvas_projects;

CREATE TABLE canvas_selections_v2 (project TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO canvas_selections_v2 (project,data) SELECT project,data FROM canvas_selections;

DROP TABLE canvas_selections;

ALTER TABLE canvas_selections_v2 RENAME TO canvas_selections;

CREATE TABLE creation_decisions_v2 (scope TEXT NOT NULL, id TEXT NOT NULL, signature TEXT NOT NULL, reserve INTEGER NOT NULL CHECK(reserve>=0), data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(scope,id));

INSERT INTO creation_decisions_v2 (scope,id,signature,reserve,data) SELECT scope,id,signature,reserve,data FROM creation_decisions;

DROP TABLE creation_decisions;

ALTER TABLE creation_decisions_v2 RENAME TO creation_decisions;

CREATE TABLE creator_jobs_v2 (id TEXT NOT NULL PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(project) REFERENCES creator_projects(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO creator_jobs_v2 (id,project,data) SELECT id,project,data FROM creator_jobs;

DROP TABLE creator_jobs;

ALTER TABLE creator_jobs_v2 RENAME TO creator_jobs;

CREATE TABLE creator_projects_v2 (id TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO creator_projects_v2 (id,data) SELECT id,data FROM creator_projects;

DROP TABLE creator_projects;

ALTER TABLE creator_projects_v2 RENAME TO creator_projects;

CREATE TABLE file_objects_v2 (
    id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=64 AND id NOT GLOB '*[^0-9a-f]*' AND id=sha256), backend TEXT NOT NULL,
    storage_key TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    bytes INTEGER NOT NULL CHECK(bytes>0), mime TEXT NOT NULL, created_at REAL NOT NULL,
    UNIQUE(backend,storage_key)
);

INSERT INTO file_objects_v2 (id,backend,storage_key,sha256,bytes,mime,created_at) SELECT id,backend,storage_key,sha256,bytes,mime,created_at FROM file_objects;

DROP TABLE file_objects;

ALTER TABLE file_objects_v2 RENAME TO file_objects;

CREATE TABLE image_jobs_v2 (id TEXT NOT NULL PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO image_jobs_v2 (id,owner,data) SELECT id,owner,data FROM image_jobs;

DROP TABLE image_jobs;

ALTER TABLE image_jobs_v2 RENAME TO image_jobs;

CREATE TABLE media_grants_v2 (
    scope TEXT NOT NULL, object_id TEXT NOT NULL REFERENCES file_objects(id),
    PRIMARY KEY(scope,object_id)
);

INSERT INTO media_grants_v2 (scope,object_id) SELECT scope,object_id FROM media_grants;

DROP TABLE media_grants;

ALTER TABLE media_grants_v2 RENAME TO media_grants;

CREATE TABLE media_heads_v2 (
    item_id TEXT NOT NULL PRIMARY KEY REFERENCES media_items(id), revision_id TEXT NOT NULL
, FOREIGN KEY(item_id,revision_id) REFERENCES media_revisions(item_id,id));

INSERT INTO media_heads_v2 (item_id,revision_id) SELECT item_id,revision_id FROM media_heads;

DROP TABLE media_heads;

ALTER TABLE media_heads_v2 RENAME TO media_heads;

CREATE TABLE media_items_v2 (
    id TEXT NOT NULL PRIMARY KEY, scope TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL,
    UNIQUE(scope,target,kind)
);

INSERT INTO media_items_v2 (id,scope,target,kind) SELECT id,scope,target,kind FROM media_items;

DROP TABLE media_items;

ALTER TABLE media_items_v2 RENAME TO media_items;

CREATE TABLE media_revision_objects_v2 (
    revision_id TEXT NOT NULL REFERENCES media_revisions(id), object_id TEXT NOT NULL REFERENCES file_objects(id),
    PRIMARY KEY(revision_id,object_id)
);

INSERT INTO media_revision_objects_v2 (revision_id,object_id) SELECT revision_id,object_id FROM media_revision_objects;

DROP TABLE media_revision_objects;

ALTER TABLE media_revision_objects_v2 RENAME TO media_revision_objects;

CREATE TABLE media_revisions_v2 (
    id TEXT NOT NULL PRIMARY KEY, item_id TEXT NOT NULL REFERENCES media_items(id),
    parent_id TEXT CHECK(parent_id IS NULL OR parent_id<>id), content_hash TEXT NOT NULL CHECK(length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
    data TEXT NOT NULL CHECK(json_valid(data)), label TEXT NOT NULL, created_at REAL NOT NULL
, UNIQUE(item_id,id), FOREIGN KEY(item_id,parent_id) REFERENCES media_revisions(item_id,id));

INSERT INTO media_revisions_v2 (id,item_id,parent_id,content_hash,data,label,created_at) SELECT id,item_id,parent_id,content_hash,data,label,created_at FROM media_revisions;

DROP TABLE media_revisions;

ALTER TABLE media_revisions_v2 RENAME TO media_revisions;

CREATE TABLE studio_image_requests_v2 (workspace TEXT NOT NULL, id TEXT NOT NULL, signature TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(workspace,id), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO studio_image_requests_v2 (workspace,id,signature,data) SELECT workspace,id,signature,data FROM studio_image_requests;

DROP TABLE studio_image_requests;

ALTER TABLE studio_image_requests_v2 RENAME TO studio_image_requests;

CREATE TABLE studio_limits_v2 (workspace TEXT NOT NULL PRIMARY KEY, calls INTEGER NOT NULL CHECK(calls>=0));

INSERT INTO studio_limits_v2 (workspace,calls) SELECT workspace,calls FROM studio_limits;

DROP TABLE studio_limits;

ALTER TABLE studio_limits_v2 RENAME TO studio_limits;

CREATE TABLE studio_links_v2 (workspace TEXT NOT NULL PRIMARY KEY, chat_id TEXT NOT NULL, FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO studio_links_v2 (workspace,chat_id) SELECT workspace,chat_id FROM studio_links;

DROP TABLE studio_links;

ALTER TABLE studio_links_v2 RENAME TO studio_links;

CREATE TABLE studio_projects_v2 (workspace TEXT NOT NULL PRIMARY KEY, name TEXT NOT NULL, origin TEXT CHECK(origin IS NULL OR json_valid(origin)), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO studio_projects_v2 (workspace,name,origin) SELECT workspace,name,origin FROM studio_projects;

DROP TABLE studio_projects;

ALTER TABLE studio_projects_v2 RENAME TO studio_projects;

CREATE TABLE studio_reservations_v2 (workspace TEXT NOT NULL, job TEXT NOT NULL PRIMARY KEY);

INSERT INTO studio_reservations_v2 (workspace,job) SELECT workspace,job FROM studio_reservations;

DROP TABLE studio_reservations;

ALTER TABLE studio_reservations_v2 RENAME TO studio_reservations;

CREATE TABLE studio_video_jobs_v2 (id TEXT NOT NULL PRIMARY KEY,workspace TEXT NOT NULL,data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO studio_video_jobs_v2 (id,workspace,data) SELECT id,workspace,data FROM studio_video_jobs;

DROP TABLE studio_video_jobs;

ALTER TABLE studio_video_jobs_v2 RENAME TO studio_video_jobs;

CREATE TABLE studio_video_renders_v2 (id TEXT NOT NULL PRIMARY KEY,workspace TEXT NOT NULL,data TEXT NOT NULL CHECK(json_valid(data)), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO studio_video_renders_v2 (id,workspace,data) SELECT id,workspace,data FROM studio_video_renders;

DROP TABLE studio_video_renders;

ALTER TABLE studio_video_renders_v2 RENAME TO studio_video_renders;

CREATE TABLE turns_v2 (row_id INTEGER NOT NULL PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO turns_v2 (row_id,owner,data) SELECT row_id,owner,data FROM turns;

DROP TABLE turns;

ALTER TABLE turns_v2 RENAME TO turns;

CREATE TABLE video_precision_links_v2
                  (workspace TEXT NOT NULL, object_id TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), project_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.project')) STORED NOT NULL REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY(workspace,object_id));

INSERT INTO video_precision_links_v2 (workspace,object_id,data) SELECT workspace,object_id,data FROM video_precision_links;

DROP TABLE video_precision_links;

ALTER TABLE video_precision_links_v2 RENAME TO video_precision_links;

CREATE TABLE video_precision_requests_v2
                  (project TEXT NOT NULL, request_id TEXT NOT NULL, signature TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)),
                   PRIMARY KEY(project,request_id), FOREIGN KEY(project) REFERENCES canvas_projects(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO video_precision_requests_v2 (project,request_id,signature,data) SELECT project,request_id,signature,data FROM video_precision_requests;

DROP TABLE video_precision_requests;

ALTER TABLE video_precision_requests_v2 RENAME TO video_precision_requests;

CREATE TABLE video_workspace_receipts_v2 (workspace TEXT NOT NULL, id TEXT NOT NULL, signature TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), PRIMARY KEY(workspace,id), FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO video_workspace_receipts_v2 (workspace,id,signature,data) SELECT workspace,id,signature,data FROM video_workspace_receipts;

DROP TABLE video_workspace_receipts;

ALTER TABLE video_workspace_receipts_v2 RENAME TO video_workspace_receipts;

CREATE TABLE video_workspaces_v2 (id TEXT NOT NULL PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));

INSERT INTO video_workspaces_v2 (id,data) SELECT id,data FROM video_workspaces;

DROP TABLE video_workspaces;

ALTER TABLE video_workspaces_v2 RENAME TO video_workspaces;

CREATE TABLE workspace_snapshots_v2 (
    id TEXT NOT NULL PRIMARY KEY, workspace TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
    data TEXT NOT NULL CHECK(json_valid(data)), created_at REAL NOT NULL
, FOREIGN KEY(workspace) REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED);

INSERT INTO workspace_snapshots_v2 (id,workspace,revision,data,created_at) SELECT id,workspace,revision,data,created_at FROM workspace_snapshots;

DROP TABLE workspace_snapshots;

ALTER TABLE workspace_snapshots_v2 RENAME TO workspace_snapshots;

CREATE INDEX attachments_owner ON attachments(owner);

CREATE INDEX turns_owner ON turns(owner);

CREATE INDEX image_jobs_owner ON image_jobs(owner);

CREATE INDEX canvas_jobs_project ON canvas_jobs(project);

CREATE INDEX canvas_plans_project ON canvas_plans(project);

CREATE INDEX creator_jobs_project ON creator_jobs(project);

CREATE INDEX studio_video_jobs_workspace ON studio_video_jobs(workspace);

CREATE INDEX studio_video_renders_workspace ON studio_video_renders(workspace);

CREATE INDEX studio_reservations_workspace ON studio_reservations(workspace);

CREATE INDEX video_precision_project ON video_precision_links(json_extract(data,'$.project'));

CREATE INDEX media_grants_object ON media_grants(object_id);

CREATE INDEX media_revisions_item_time ON media_revisions(item_id,created_at);

CREATE INDEX media_revisions_item_file ON media_revisions(item_id,json_extract(data,'$.file'));

CREATE INDEX media_revision_objects_object ON media_revision_objects(object_id);

CREATE INDEX workspace_snapshots_workspace_revision ON workspace_snapshots(workspace,revision);

CREATE TABLE workspace_catalog (
    workspace TEXT PRIMARY KEY NOT NULL REFERENCES video_workspaces(id) DEFERRABLE INITIALLY DEFERRED,
    name TEXT NOT NULL, updated_at REAL NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
    cover TEXT, plan TEXT NOT NULL, notes INTEGER NOT NULL CHECK(notes>=0),
    pictures INTEGER NOT NULL CHECK(pictures>=0), shots INTEGER NOT NULL CHECK(shots>=0),
    adopted INTEGER NOT NULL CHECK(adopted>=0)
);

CREATE INDEX workspace_catalog_updated ON workspace_catalog(updated_at DESC,workspace);

CREATE INDEX studio_links_chat ON studio_links(chat_id,workspace);

INSERT INTO workspace_catalog SELECT w.id,coalesce(nullif(p.name,''),nullif(json_extract(w.data,'$.state.notes[0].title'),''),nullif(json_extract(w.data,'$.state.shots[0].name'),''),'未命名画布'),
    coalesce(json_extract(w.data,'$.updated_at'),0),json_extract(w.data,'$.revision'),
    (SELECT json_extract(a.value,'$.file') FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL LIMIT 1),
    substr(coalesce(json_extract(w.data,'$.state.notes[0].text'),''),1,220),
    coalesce(json_array_length(w.data,'$.state.notes'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.assets') a WHERE json_extract(a.value,'$.file') IS NOT NULL),
    coalesce(json_array_length(w.data,'$.state.shots'),0),
    (SELECT count(*) FROM json_each(w.data,'$.state.sequence') a WHERE a.type='object' AND json_extract(a.value,'$.job') IS NOT NULL)
    FROM video_workspaces w LEFT JOIN studio_projects p ON p.workspace=w.id;

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

CREATE TRIGGER protect_media_revision_update BEFORE UPDATE ON media_revisions BEGIN
    SELECT RAISE(ABORT,'content versions are immutable'); END;

CREATE TRIGGER protect_media_revision_delete BEFORE DELETE ON media_revisions BEGIN
    SELECT RAISE(ABORT,'content versions must be retained'); END;
