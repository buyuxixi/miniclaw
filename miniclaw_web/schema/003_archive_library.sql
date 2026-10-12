CREATE TABLE project_archive (
    workspace TEXT NOT NULL PRIMARY KEY REFERENCES video_workspaces(id),
    archived_at REAL NOT NULL
);

CREATE TABLE library_items (
    object_id TEXT NOT NULL PRIMARY KEY REFERENCES file_objects(id),
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    kind TEXT NOT NULL CHECK(kind IN ('image','video')),
    source_workspace TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX library_items_created ON library_items(created_at DESC,object_id);
