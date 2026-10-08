-- Business database only. Hermes state.db is intentionally independent.
CREATE TABLE file_objects (
    id TEXT PRIMARY KEY CHECK(length(id)=64), backend TEXT NOT NULL,
    storage_key TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    bytes INTEGER NOT NULL CHECK(bytes>0), mime TEXT NOT NULL, created_at REAL NOT NULL,
    UNIQUE(backend,storage_key)
);
CREATE TABLE media_items (
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL,
    UNIQUE(scope,target,kind)
);
CREATE TABLE media_revisions (
    id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES media_items(id),
    parent_id TEXT REFERENCES media_revisions(id), content_hash TEXT NOT NULL,
    data TEXT NOT NULL, label TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX media_revisions_item_time ON media_revisions(item_id,created_at);
CREATE TABLE media_heads (
    item_id TEXT PRIMARY KEY REFERENCES media_items(id), revision_id TEXT NOT NULL REFERENCES media_revisions(id)
);
CREATE TABLE media_revision_objects (
    revision_id TEXT NOT NULL REFERENCES media_revisions(id), object_id TEXT NOT NULL REFERENCES file_objects(id),
    PRIMARY KEY(revision_id,object_id)
);
CREATE INDEX media_revision_objects_object ON media_revision_objects(object_id);
CREATE TABLE media_grants (
    scope TEXT NOT NULL, object_id TEXT NOT NULL REFERENCES file_objects(id),
    PRIMARY KEY(scope,object_id)
);
CREATE TABLE workspace_snapshots (
    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, revision INTEGER NOT NULL,
    data TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX workspace_snapshots_workspace_revision ON workspace_snapshots(workspace,revision);
