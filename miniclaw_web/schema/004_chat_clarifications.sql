CREATE TABLE chat_tasks (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL, updated REAL NOT NULL
);
CREATE INDEX chat_tasks_owner ON chat_tasks(owner, updated);
CREATE TABLE chat_clarifications (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES chat_tasks(id),
 owner TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 deadline REAL NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL
);
CREATE UNIQUE INDEX chat_one_question ON chat_clarifications(task_id)
 WHERE status IN ('prepared','pending');
CREATE TABLE chat_resume_jobs (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES chat_tasks(id),
 clarification_id TEXT NOT NULL UNIQUE REFERENCES chat_clarifications(id),
 status TEXT NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL
);
CREATE TABLE chat_operations (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES chat_tasks(id),
 status TEXT NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL
);
