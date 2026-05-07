"""Build a deterministic SQLite index (FTS5 + JSON1)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .graph import Graph


def build(graph: Graph, db_path: Path) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        _schema(conn)
        _populate(conn, graph)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE fields (
            schema_file TEXT,
            path TEXT,
            business_key TEXT,
            type_fqn TEXT,
            PRIMARY KEY (schema_file, path)
        );
        CREATE INDEX idx_fields_bk ON fields(business_key);

        CREATE TABLE mappers (
            mapper_id TEXT PRIMARY KEY,
            mapper_kind TEXT,
            project_id TEXT,
            repo_id TEXT,
            pair_id TEXT,
            edge_count INTEGER
        );

        CREATE TABLE edges (
            edge_id TEXT PRIMARY KEY,
            mapper_id TEXT,
            mapper_kind TEXT,
            kind TEXT,
            source_schema TEXT,
            source_path TEXT,
            source_bk TEXT,
            target_schema TEXT,
            target_path TEXT,
            target_bk TEXT,
            expression TEXT,
            confidence TEXT,
            file TEXT,
            line INTEGER,
            scope_json TEXT,
            git_json TEXT
        );
        CREATE INDEX idx_edges_mapper ON edges(mapper_id);
        CREATE INDEX idx_edges_target_bk ON edges(target_bk);
        CREATE INDEX idx_edges_source_bk ON edges(source_bk);

        CREATE VIRTUAL TABLE edges_fts USING fts5(
            edge_id, source_path, target_path, expression, mapper_id, source_bk, target_bk,
            tokenize='unicode61'
        );
        """
    )


def _populate(conn: sqlite3.Connection, graph: Graph) -> None:
    conn.executemany(
        "INSERT INTO fields VALUES (?, ?, ?, ?)",
        sorted(
            (
                (f.schemaFile, f.path, f.business_key, f.type_fqn)
                for f in graph.fields.values()
            ),
            key=lambda r: (r[0], r[1]),
        ),
    )
    conn.executemany(
        "INSERT INTO mappers VALUES (?, ?, ?, ?, ?, ?)",
        sorted(
            (
                (m.mapper_id, m.mapper_kind, m.project_id, m.repo_id, m.pair_id, len(m.edges))
                for m in graph.mappers.values()
            ),
            key=lambda r: r[0],
        ),
    )
    rows = []
    fts_rows = []
    for e in sorted(graph.edges, key=lambda x: x.edgeId):
        source_bk = (
            graph.fields[(e.source.schemaFile, e.source.path)].business_key
            if e.source else None
        )
        target_bk = graph.fields[(e.target.schemaFile, e.target.path)].business_key
        rows.append((
            e.edgeId, e.mapperId, e.mapperKind, e.kind,
            e.source.schemaFile if e.source else None,
            e.source.path if e.source else None,
            source_bk,
            e.target.schemaFile, e.target.path, target_bk,
            e.expression, e.confidence,
            e.git.file, e.git.line,
            json.dumps(e.scope or {}, sort_keys=True),
            json.dumps(e.git.model_dump(exclude_none=True), sort_keys=True),
        ))
        fts_rows.append((
            e.edgeId,
            e.source.path if e.source else "",
            e.target.path,
            e.expression or "",
            e.mapperId,
            source_bk or "",
            target_bk or "",
        ))
    conn.executemany(
        "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.executemany(
        "INSERT INTO edges_fts (edge_id, source_path, target_path, expression, mapper_id, source_bk, target_bk) "
        "VALUES (?,?,?,?,?,?,?)", fts_rows
    )
