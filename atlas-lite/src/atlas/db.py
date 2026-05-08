"""SQLite schema + snapshot helpers. Single source of truth for atlas-lite."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshot (
    atlas_sha       TEXT PRIMARY KEY,
    built_at        TEXT NOT NULL,
    extractor_ver   TEXT NOT NULL,
    edge_count      INTEGER NOT NULL,
    mapper_count    INTEGER NOT NULL,
    field_count     INTEGER NOT NULL,
    test_count      INTEGER NOT NULL,
    invariants_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repo (
    id              TEXT PRIMARY KEY,
    project         TEXT,
    branch          TEXT NOT NULL,
    sha             TEXT NOT NULL,
    browse_template TEXT
);

CREATE TABLE IF NOT EXISTS schema (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    file            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field (
    id              TEXT PRIMARY KEY,
    schema_id       TEXT NOT NULL,
    path            TEXT NOT NULL,
    business_key    TEXT,
    type            TEXT,
    UNIQUE(schema_id, path)
);
CREATE INDEX IF NOT EXISTS idx_field_business_key ON field(business_key);

CREATE TABLE IF NOT EXISTS mapper (
    id                 TEXT PRIMARY KEY,
    fqn                TEXT NOT NULL,
    kind               TEXT NOT NULL,
    pair_id            TEXT NOT NULL,
    repo_id            TEXT NOT NULL,
    file               TEXT NOT NULL,
    sha                TEXT NOT NULL,
    browse_url         TEXT NOT NULL,
    scope_common       INTEGER NOT NULL DEFAULT 0,
    scope_country      TEXT,
    scope_clearing     TEXT,
    scope_product      TEXT,
    scope_field_group  TEXT
);
CREATE INDEX IF NOT EXISTS idx_mapper_pair      ON mapper(pair_id);
CREATE INDEX IF NOT EXISTS idx_mapper_country   ON mapper(scope_country);
CREATE INDEX IF NOT EXISTS idx_mapper_clearing  ON mapper(scope_clearing);

-- A transformation entry point: a top-level public method that takes one or
-- more source schemas and returns a target schema. This is the unit a
-- Business Analyst reasons about — Markdown, coverage, impact analysis, and
-- the future UI/graph all pivot around entry points, not classes or files.
CREATE TABLE IF NOT EXISTS entry_point (
    id                TEXT PRIMARY KEY,
    pair_id           TEXT NOT NULL,
    repo_id           TEXT NOT NULL,
    class_fqn         TEXT NOT NULL,
    method_name       TEXT NOT NULL,
    method_signature  TEXT NOT NULL,        -- full Java signature line
    source_schema_ids TEXT NOT NULL,        -- JSON array
    target_schema_id  TEXT NOT NULL,
    file              TEXT NOT NULL,
    line              INTEGER NOT NULL,
    sha               TEXT NOT NULL,
    browse_url        TEXT NOT NULL,
    scope_common      INTEGER NOT NULL DEFAULT 0,
    scope_country     TEXT,
    scope_clearing    TEXT,
    scope_product     TEXT,
    scope_field_group TEXT,
    edge_count        INTEGER NOT NULL DEFAULT 0,
    coverage_percent  REAL
);
CREATE INDEX IF NOT EXISTS idx_entry_point_pair      ON entry_point(pair_id);
CREATE INDEX IF NOT EXISTS idx_entry_point_class     ON entry_point(class_fqn);
CREATE INDEX IF NOT EXISTS idx_entry_point_country   ON entry_point(scope_country);
CREATE INDEX IF NOT EXISTS idx_entry_point_clearing  ON entry_point(scope_clearing);
CREATE INDEX IF NOT EXISTS idx_entry_point_product   ON entry_point(scope_product);

CREATE TABLE IF NOT EXISTS edge (
    id                TEXT PRIMARY KEY,
    pair_id           TEXT NOT NULL,
    mapper_id         TEXT NOT NULL,
    entry_point_id    TEXT,
    source_field_id   TEXT,
    target_field_id   TEXT NOT NULL,
    kind              TEXT NOT NULL,
    expression        TEXT NOT NULL,
    static_helper_fqn TEXT,
    format_spec_json  TEXT,
    file              TEXT NOT NULL,
    line              INTEGER NOT NULL,
    sha               TEXT NOT NULL,
    browse_url        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edge_source       ON edge(source_field_id);
CREATE INDEX IF NOT EXISTS idx_edge_target       ON edge(target_field_id);
CREATE INDEX IF NOT EXISTS idx_edge_mapper       ON edge(mapper_id);
CREATE INDEX IF NOT EXISTS idx_edge_pair         ON edge(pair_id);
CREATE INDEX IF NOT EXISTS idx_edge_entry_point  ON edge(entry_point_id);
CREATE INDEX IF NOT EXISTS idx_edge_helper       ON edge(static_helper_fqn);

CREATE TABLE IF NOT EXISTS test (
    id              TEXT PRIMARY KEY,
    fqn             TEXT NOT NULL,
    file            TEXT NOT NULL,
    line            INTEGER NOT NULL,
    sha             TEXT NOT NULL,
    browse_url      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edge_test (
    edge_id         TEXT NOT NULL,
    test_id         TEXT NOT NULL,
    PRIMARY KEY (edge_id, test_id)
);

-- Per-edge resolution trail. Each row is one step Atlas walked through to
-- resolve the source path: setter site, wrapper-arg, qualifier method body,
-- static-helper body, intra-class helper body. seq is 0-indexed in walk order.
CREATE TABLE IF NOT EXISTS edge_resolution (
    edge_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,        -- direct | wrapper_arg | qualifier | static_call | intra_class
    file       TEXT NOT NULL,
    line       INTEGER NOT NULL,
    snippet    TEXT NOT NULL,
    helper_fqn TEXT,
    PRIMARY KEY (edge_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_edge_resolution_helper ON edge_resolution(helper_fqn);

-- Helper method bodies, deduplicated by FQN. Captured during extraction the
-- first time each helper is walked. Markdown render inlines `body` verbatim
-- under each qualifier/static_call edge so a Business Analyst sees the full
-- resolution logic, not just the call expression.
CREATE TABLE IF NOT EXISTS helper (
    fqn         TEXT PRIMARY KEY,
    file        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    signature   TEXT NOT NULL,
    body        TEXT NOT NULL,
    body_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage (
    repo_id           TEXT NOT NULL,
    pair_id           TEXT NOT NULL,
    files_scanned     INTEGER NOT NULL,
    mappers_detected  INTEGER NOT NULL,
    edges_emitted     INTEGER NOT NULL,
    unparseable_json  TEXT NOT NULL,
    unmatched_json    TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (repo_id, pair_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS field_fts  USING fts5(field_id UNINDEXED, schema, path, business_key, type);
CREATE VIRTUAL TABLE IF NOT EXISTS mapper_fts USING fts5(mapper_id UNINDEXED, fqn, scope_text);
"""


def open_db(path: Path | str) -> sqlite3.Connection:
    """Open (and create) an Atlas Lite database at the given path."""
    p = Path(os.path.expanduser(str(path)))
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """Drop and recreate every table. Used by full extracts."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        if t.startswith("sqlite_"):
            continue
        cur.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()
    init_schema(conn)
