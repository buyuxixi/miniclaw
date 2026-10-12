CREATE TABLE attachment_uploads (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL,
    signature TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
    part_size INTEGER NOT NULL, state TEXT NOT NULL, attachment_id TEXT,
    error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
    UNIQUE(owner,request_id)
);
CREATE TABLE attachment_upload_parts (
    upload_id TEXT NOT NULL REFERENCES attachment_uploads(id) ON DELETE CASCADE,
    part_no INTEGER NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
    path TEXT NOT NULL, PRIMARY KEY(upload_id,part_no)
);
CREATE INDEX attachment_upload_owner_state ON attachment_uploads(owner,state,updated_at);
CREATE TABLE document_parses (
    attachment_id TEXT PRIMARY KEY REFERENCES attachments(id), owner TEXT NOT NULL,
    object_id TEXT NOT NULL REFERENCES file_objects(id), parser_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','parsing','ready','partial','failed','cancelled')),
    attempt INTEGER NOT NULL DEFAULT 0, chunk_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0, units_seen INTEGER NOT NULL DEFAULT 0,
    units_done INTEGER NOT NULL DEFAULT 0,
    warnings TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(warnings)),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata)), error TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX document_parse_queue ON document_parses(owner,state,created_at);
CREATE TABLE document_chunks (
    id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL REFERENCES document_parses(attachment_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL CHECK(json_valid(source)),
    UNIQUE(attachment_id,ordinal)
);
CREATE INDEX document_chunk_order ON document_chunks(attachment_id,ordinal);
CREATE TABLE document_rows (
    attachment_id TEXT NOT NULL REFERENCES document_parses(attachment_id) ON DELETE CASCADE,
    table_name TEXT NOT NULL, row_number INTEGER NOT NULL, cells TEXT NOT NULL CHECK(json_valid(cells)),
    source TEXT NOT NULL CHECK(json_valid(source)), PRIMARY KEY(attachment_id,table_name,row_number)
);
CREATE TABLE document_analysis_jobs (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, signature TEXT NOT NULL,
    mode TEXT NOT NULL, question TEXT NOT NULL, manifest TEXT NOT NULL CHECK(json_valid(manifest)),
    state TEXT NOT NULL, max_calls INTEGER NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
    reserved_bytes INTEGER NOT NULL DEFAULT 0, max_input_bytes INTEGER NOT NULL DEFAULT 16777216,
    result TEXT, error TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(owner,request_id)
);
CREATE TABLE document_analysis_steps (
    job_id TEXT NOT NULL REFERENCES document_analysis_jobs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, phase TEXT NOT NULL, input TEXT NOT NULL CHECK(json_valid(input)),
    state TEXT NOT NULL, output TEXT, error TEXT, PRIMARY KEY(job_id,ordinal)
);
CREATE INDEX document_analysis_queue ON document_analysis_jobs(state,created_at);
