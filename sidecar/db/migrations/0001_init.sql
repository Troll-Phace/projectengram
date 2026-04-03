-- 0001_init.sql — Initial schema for Engram
--
-- NOTE: PRAGMA foreign_keys = ON must be set at connection time,
-- not in this migration. See engine.py for the SQLAlchemy event listener.

BEGIN;

-- =============================================================================
-- 1. projects — Each coding project discovered or manually added
-- =============================================================================
CREATE TABLE projects (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    path                 TEXT UNIQUE,
    description          TEXT,
    status               TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active', 'paused', 'archived', 'idea')),
    primary_language     TEXT,
    languages            TEXT,            -- JSON object: {"typescript": 0.65, "css": 0.20}
    frameworks           TEXT,            -- JSON array:  ["react", "tailwind", "vite"]
    package_manager      TEXT,
    loc                  INTEGER,
    file_count           INTEGER,
    size_bytes           INTEGER,
    git_remote_url       TEXT,
    git_branch           TEXT,
    git_dirty            INTEGER NOT NULL DEFAULT 0,
    git_last_commit_hash TEXT,
    git_last_commit_date TEXT,            -- ISO 8601 datetime
    git_last_commit_msg  TEXT,
    git_branch_count     INTEGER,
    color_override       TEXT,
    icon_override        TEXT,
    notes                TEXT,
    missing              INTEGER NOT NULL DEFAULT 0,
    deleted_at           TEXT,            -- ISO 8601 datetime; NULL = active
    last_scanned_at      TEXT,            -- ISO 8601 datetime
    last_opened_at       TEXT,            -- ISO 8601 datetime
    created_at           TEXT NOT NULL,   -- ISO 8601 datetime
    updated_at           TEXT NOT NULL    -- ISO 8601 datetime
);

CREATE INDEX idx_projects_path                  ON projects (path);
CREATE INDEX idx_projects_status                ON projects (status);
CREATE INDEX idx_projects_primary_language      ON projects (primary_language);
CREATE INDEX idx_projects_git_last_commit_date  ON projects (git_last_commit_date);
CREATE INDEX idx_projects_deleted_at            ON projects (deleted_at);

-- =============================================================================
-- 2. edges — Relationships between projects (auto-computed or manual)
-- =============================================================================
CREATE TABLE edges (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    target_id       TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL
                    CHECK (edge_type IN ('auto_tech', 'auto_dep', 'manual')),
    weight          REAL NOT NULL,
    label           TEXT,
    color_override  TEXT,
    directed        INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT,                -- JSON object
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (source_id, target_id, edge_type)
);

CREATE INDEX idx_edges_source_id ON edges (source_id);
CREATE INDEX idx_edges_target_id ON edges (target_id);

-- =============================================================================
-- 3. tags — User-defined labels for projects
-- =============================================================================
CREATE TABLE tags (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT,
    created_at  TEXT NOT NULL
);

-- =============================================================================
-- 4. project_tags — Many-to-many join: projects <-> tags
-- =============================================================================
CREATE TABLE project_tags (
    project_id  TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    tag_id      TEXT NOT NULL REFERENCES tags (id)     ON DELETE CASCADE,
    PRIMARY KEY (project_id, tag_id)
);

-- =============================================================================
-- 5. clusters — Visual groupings on the graph canvas
-- =============================================================================
CREATE TABLE clusters (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    color       TEXT,
    opacity     REAL NOT NULL DEFAULT 0.15,
    collapsed   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- =============================================================================
-- 6. project_clusters — Many-to-many join: projects <-> clusters
-- =============================================================================
CREATE TABLE project_clusters (
    project_id  TEXT NOT NULL REFERENCES projects (id)  ON DELETE CASCADE,
    cluster_id  TEXT NOT NULL REFERENCES clusters (id)  ON DELETE CASCADE,
    PRIMARY KEY (project_id, cluster_id)
);

-- =============================================================================
-- 7. node_positions — Persisted x/y positions for the graph layout
-- =============================================================================
CREATE TABLE node_positions (
    project_id  TEXT PRIMARY KEY REFERENCES projects (id) ON DELETE CASCADE,
    x           REAL NOT NULL,
    y           REAL NOT NULL,
    pinned      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

-- =============================================================================
-- 8. config — Key-value application settings
-- =============================================================================
CREATE TABLE config (
    key         TEXT PRIMARY KEY,
    value       TEXT,                    -- JSON string
    updated_at  TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- Default configuration entries
-- -----------------------------------------------------------------------------
INSERT INTO config (key, value, updated_at) VALUES
    ('projects_root',          '"~/Documents"',  datetime('now')),
    ('auto_edge_min_weight',   '0.3',            datetime('now')),
    ('scan_interval_minutes',  '30',             datetime('now')),
    ('sidecar_port',           '9721',           datetime('now'));

COMMIT;

-- PRAGMA must be outside the transaction — SQLite does not allow it inside BEGIN/COMMIT.
PRAGMA user_version = 1;
