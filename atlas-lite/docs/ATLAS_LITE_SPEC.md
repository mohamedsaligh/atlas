# Atlas Lite — Design & Implementation Spec

> A deterministic, hallucination-proof knowledge platform for cross-service mapping lineage with **100% end-to-end traceability**.
> This document is the kickoff prompt for Claude Code. Read it end-to-end before writing any file.

**Version:** 2.0 (replaces ATLAS_SPEC.md v1.0)
**Stack:** Python 3.12 (back-end + extractor) + React/TypeScript (UI). No Java code; no Maven plugin.
**Target audience:** Claude Code (autonomous build agent). Reviewed by senior engineering.

---

## Table of contents

1. [The 100% traceability guarantee](#1-the-100-traceability-guarantee)
2. [Why this is simple](#2-why-this-is-simple)
3. [Repository layout](#3-repository-layout)
4. [Configuration (`atlas.yml`)](#4-configuration-atlasyml)
5. [The extractor — the only thing that's hard](#5-the-extractor--the-only-thing-thats-hard)
6. [SQLite schema — the single source of truth](#6-sqlite-schema--the-single-source-of-truth)
7. [Renderer — SQLite to Markdown site](#7-renderer--sqlite-to-markdown-site)
8. [MCP server + REST shim + Bitbucket helpers](#8-mcp-server--rest-shim--bitbucket-helpers)
9. [Validator — 30 lines](#9-validator--30-lines)
10. [Auto-learning — one cron line](#10-auto-learning--one-cron-line)
11. [Web UI](#11-web-ui)
12. [Testing strategy](#12-testing-strategy)
13. [Two-week build plan](#13-two-week-build-plan)
14. [Worked example — full end-to-end trace](#14-worked-example--full-end-to-end-trace)
15. [Claude Code kickoff prompt](#15-claude-code-kickoff-prompt)

---

## 1. The 100% traceability guarantee

Every fact Atlas can ever produce — every edge, every mapper, every field, every test, every UI cell, every MCP response — carries the same provenance tuple:

```
{ repo_id, sha, file, line, browse_url }
```

This tuple is captured by the extractor at write time, stored in SQLite, and threaded through every read path. The agent and the UI cannot produce output that lacks it; the validator rejects any draft that does.

End-to-end means:

- **Field-level.** Source field → target field, with the exact line of Java that performed the assignment, pinned to a Bitbucket SHA.
- **Service-to-service.** Cross-pair joins through `business_key` on shared fields compose into multi-hop paths (e.g. inbound MT103 → payment local → sanctions fixed-length → fraud JSON).
- **Code-to-test.** Every edge links to the JUnit method(s) that exercise it.
- **Snapshot-pinned.** Every MCP/REST response carries an `atlas_sha`; pinning that SHA replays the exact same answer forever.
- **No cell without a click.** Every value in the UI is one click from the Bitbucket line that produced it.

**If Atlas can't trace it, Atlas doesn't show it.** That's the rule.

---

## 2. Why this is simple

The accuracy story rests on a single technical decision:

> Parse MapStruct's **generated** `*Impl.java` files, not the annotated interfaces.

When `mvn compile` runs, MapStruct's annotation processor writes plain Java that looks like this:

```java
target.setIban( src.getField50K().substring(0, 34) );
target.getDbtr().setName( src.getField50K_2() );
```

That's the mapping. Fully resolved. No annotations to interpret, no overload ambiguity, no DSL to evaluate. We just read the file with **tree-sitter** (which has a Python binding) and walk the `method_invocation` nodes that are setter calls. For your codebase that's 98% of every mapping edge in every service.

For the other 2% — sanctions fixed-length encoders, hand-written builders, tagged-format writers — the same tree-sitter walk handles three more node patterns. Same script, three more matchers.

Everything else in the system is glue around that one trick.

---

## 3. Repository layout

One Python project, one React app. That's it.

```
atlas/
├── atlas.yml                       # user config (commit a sample at examples/)
├── pyproject.toml                  # uv project
├── uv.lock
├── README.md
│
├── src/atlas/
│   ├── __init__.py
│   ├── config.py                   # parse + validate atlas.yml
│   ├── extract.py                  # tree-sitter Java → edges → SQLite
│   ├── schemas.py                  # parse XSD / JSON Schema / Proto / fixedlen
│   ├── db.py                       # SQLite schema, migrations, snapshot helpers
│   ├── render.py                   # SQLite → Markdown site + JSON-LD export
│   ├── mcp_server.py               # MCP server + REST shim (FastAPI)
│   ├── bitbucket.py                # bb_read_file, bb_diff, bb_create_pr (used by agent later)
│   ├── validate.py                 # transcript-based hallucination check
│   ├── scheduler.py                # APScheduler for auto-learn (optional; cron also works)
│   └── cli.py                      # `atlas extract | render | serve | scheduler`
│
├── ui/                             # React + Vite + TypeScript (see §11)
│   ├── package.json
│   └── src/
│
├── examples/
│   ├── atlas.yml                   # sample config matching §4
│   └── fixtures/                   # tiny Java projects used by tests
│       ├── tiny-mapstruct/
│       ├── tiny-fixedlen/
│       ├── tiny-builder/
│       ├── tiny-multi-pair/
│       └── tiny-broken/
│
├── schemas/
│   ├── atlas-config.schema.json
│   └── jsonld-context.json
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONFIG.md
│   ├── EXTRACTOR.md
│   ├── MCP_TOOLS.md
│   └── AGENT_INTEGRATION_TODO.md
│
└── tests/
    ├── test_config.py
    ├── test_extract.py             # determinism + golden fixtures
    ├── test_schemas.py
    ├── test_mcp.py
    ├── test_validate.py            # adversarial suite
    └── conftest.py
```

Total source files at ship: ~12 Python files + the React app. ~2,000 lines of Python, ~3,000 lines of TS/TSX.

---

## 4. Configuration (`atlas.yml`)

One file controls the entire system. Validated against `schemas/atlas-config.schema.json`.

```yaml
version: 1

# ───── Bitbucket integration ─────
bitbucket:
  base_url: https://bitbucket.x.com
  api_kind: server                              # server | cloud
  auth: { token_env: BITBUCKET_TOKEN }
  browse_template: "{base}/projects/{project}/repos/{repo}/browse/{file}?at={sha}#{line}"

# ───── Repos: where to find them on disk ─────
repos:
  - id: payment-service
    path: ~/work/payments/payment-service       # local clone root
    project: PMT
    branch: main
  - id: sanctions-service
    path: ~/work/payments/sanctions-service
    project: PMT
    branch: main
  - id: fraud-service
    path: ~/work/payments/fraud-service
    project: PMT
    branch: main

# ───── Domain-model pairs ─────
# Each pair = one analysis universe (source schema → target schema).
# Multiple pairs allowed. Pairs compose into the global graph via business_key.
pairs:
  - id: mt103_to_local
    source: { name: "SWIFT MT103", file: schemas/swift/SWIFT_MT103.xsd, kind: xsd }
    target: { name: "LocalDomain", file: schemas/local/LocalDomain.json, kind: json-schema }
    scan_globs:
      - "payment-service/**/com/x/payment/mapper/common/**/*.java"
      - "payment-service/**/com/x/payment/mapper/{country}/**/*.java"
      - "payment-service/**/com/x/payment/mapper/{country}/{clearing}/**/*.java"
      - "payment-service/**/com/x/payment/mapper/products/{product}/**/*.java"
      - "payment-service/**/com/x/payment/mapper/fields/{field_group}/**/*.java"
    # Optional explicit scope rules. If omitted, scope is inferred from {captures} in scan_globs above.
    scope_rules:
      - { glob: "**/mapper/common/**", scope: { common: true } }

  - id: local_to_sanctions
    source: { name: "LocalDomain", file: schemas/local/LocalDomain.json, kind: json-schema }
    target: { name: "SanctionsFixedLen", file: schemas/sanctions/spec.yaml, kind: fixedlen }
    scan_globs:
      - "sanctions-service/**/com/x/sanctions/encoder/common/**/*.java"
      - "sanctions-service/**/com/x/sanctions/encoder/{country}/**/*.java"

  - id: local_to_fraud
    source: { name: "LocalDomain", file: schemas/local/LocalDomain.json, kind: json-schema }
    target: { name: "FraudJson", file: schemas/fraud/v3.json, kind: json-schema }
    scan_globs:
      - "fraud-service/**/com/x/fraud/mapper/**/*.java"

# ───── Auto-learning schedule ─────
schedule:
  full: "0 2 * * 0"                # weekly Sunday 02:00 UTC
  incremental: "0 3 * * *"         # daily 03:00 UTC
  per_repo:
    payment-service: { incremental: "0 */6 * * *" }   # every 6h

# ───── Storage ─────
storage:
  db_path: ~/.atlas/atlas.db
  site_path: ~/.atlas/site            # rendered Markdown site
  cache_path: ~/.atlas/cache

# ───── Servers ─────
mcp_port: 4281
ui_port: 4280

# ───── Jira (used by agent module — placeholder for now) ─────
jira:
  base_url: https://jira.x.com
  auth: { token_env: JIRA_TOKEN }
  default_project: PAY
```

### 4.1 `{captures}` in scan_globs

Curly placeholders in `scan_globs` serve two purposes:

1. **Path matching** — `{country}` matches one path segment.
2. **Scope inference** — captured values become normalised scope tags (`sg_fast` → `SG_FAST`).

Recognised capture names: `country`, `clearing`, `product`, `field_group`. Anything else is treated as a literal path segment.

### 4.2 Auto-detection (when fields are omitted)

| Field | Auto-detect rule |
|---|---|
| `repos[].path` | scan `~/work` and `~/dev` for a directory whose name matches `repos[].id` |
| `repos[].project` | parse `.git/config` origin URL |
| `repos[].branch` | `git symbolic-ref refs/remotes/origin/HEAD` |
| `pairs[].scan_globs` | walk repo, find files containing `@Mapper` or class names ending in `Mapper`/`Encoder`/`Converter` |

Auto-detection writes its decisions to stderr in deterministic, replayable form.

---

## 5. The extractor — the only thing that's hard

**File:** `src/atlas/extract.py`
**Invocation:** `atlas extract --config atlas.yml [--pair mt103_to_local] [--repo payment-service]`

### 5.1 What it does

For each (repo, pair) combination:

1. Resolve the repo's `git rev-parse HEAD` → `sha`.
2. Walk every file matched by `pair.scan_globs`.
3. Classify each `.java` file: `mapstruct-impl | mapstruct-interface | builder | setter | fixedlen | tagged | unsupported`.
4. For each classifier, run the matching tree-sitter query to extract edges.
5. Write rows into SQLite: `mapper`, `field` (when new), `edge`, `test`, `edge_test`.
6. Record per-(repo, pair) stats in the `coverage` table.
7. **Hard-fail** if `coverage.unparseable_json` is non-empty for any (repo, pair).

### 5.2 The classifier (deterministic, first-match wins)

| Order | Classifier | Detector |
|---|---|---|
| 1 | `mapstruct-impl` | File path matches `**/target/generated-sources/annotations/**/*Impl.java` and the source contains the MapStruct `@Generated` stamp. **Preferred form — fully resolved.** |
| 2 | `mapstruct-interface` | File contains `@Mapper`, no companion `Impl` exists. Run `mvn compile -pl <module> -am` first to force generation, then re-classify. If still missing, skip with a warning recorded in `coverage`. |
| 3 | `builder` | File contains a chain of `.something(...)` ending in `.build()`, where the receiver is recognized as a builder factory. |
| 4 | `setter` | File contains assignments of the form `target.setX(...)` where `target` is a method parameter or local variable whose declared type matches a known target schema. |
| 5 | `fixedlen` | Pair's target schema is `kind: fixedlen` AND the file writes through one of: `StringBuilder`, `Formatter`, recognised pad helpers. |
| 6 | `tagged` | Pair's target schema is `kind: tagged` AND the file emits literal `tag/value` writes (e.g. `out.write("32A", value)`). |
| 7 | `unsupported` | Anything else. Written to `coverage.unparseable_json`. **Build fails.** |

### 5.3 Edge extraction (the heart of it)

For **mapstruct-impl** and **setter** kinds, one tree-sitter query covers them both:

```python
SETTER_QUERY = JAVA.query("""
(method_invocation
  object: (_) @receiver
  name: (identifier) @method
  arguments: (argument_list . (_) @arg .)
) @call
""")

def extract_setter_edges(tree, file_bytes, ctx):
    for match in SETTER_QUERY.matches(tree.root_node):
        method_name = text(match["method"], file_bytes)
        if not re.match(r"^set[A-Z]\w*$", method_name):
            continue
        target_path = resolve_target_path(match["receiver"], file_bytes)  # e.g. "dbtr.acct.iban"
        source_expr = text(match["arg"], file_bytes)
        kind = classify_kind(match["arg"])  # rename | constant | format | expression | concat | ...
        yield Edge(
            target_path=target_path,
            source_expr=source_expr,
            kind=kind,
            file=ctx.relpath,
            line=match["call"].start_point[0] + 1,
            sha=ctx.sha,
            mapper_id=ctx.mapper_id,
        )
```

`resolve_target_path` walks the receiver chain (`target.getDbtr().getAcct()`) and joins method-name-stripped paths with dots. `classify_kind` inspects the argument AST node:

| AST node | `kind` |
|---|---|
| `identifier` or `field_access` matching `src\.get[A-Z]\w*\(\)` (single chain) | `rename` |
| `string_literal` / `decimal_integer_literal` / `null_literal` | `constant` |
| `binary_expression` with `+` and string operands | `concat` |
| `method_invocation` ending in `.substring(...)` / `.format(...)` / `.toString()` | `format` |
| `ternary_expression` | `expression` |
| `method_invocation` to an external class (e.g. `Lookups.resolve(src.getX())`) | `lookup` (record `static_helper_fqn`) |
| anything else | `expression` |

For **builder**: the same query, but the receiver is `someBuilder` and the method is **not** prefixed with `set`. The method name *is* the target field path (e.g. `.iban(src.getField50K())` → target `iban`).

For **fixedlen**: a separate query matching `out.write(<offset_or_format>, <source_expr>)` patterns. The pair's target schema (a YAML spec listing tag/offset/length tuples) supplies the canonical target field for each offset.

For **tagged**: matches `out.write(<tag_literal>, <source_expr>)` directly.

### 5.4 Source field resolution

For each `<source_expr>` we identify the source field by:

1. Pulling out every `src.getX().getY()...` chain.
2. Joining method-name-stripped paths into a dotted path (`getField50K` → `field_50K`).
3. Looking up that path in the pair's source schema.
4. If found: link `edge.source_field_id` to it. If not: leave null and mark `kind = expression`.

For `constant` edges, `source_field_id` is null by design.

### 5.5 Test discovery

Walk `src/test/java/**`. For each `@Test` method:

1. Find which mapper class it instantiates (`new SwiftMt103ToLocalDomainMapperImpl()` or `Mappers.getMapper(...)`).
2. Find the assertion target paths (`assertEquals(..., result.getDbtr().getAcct().getIban())`).
3. Link to every edge in that mapper whose `target_path` matches an assertion path.
4. Honor `@AtlasCovers("e_001,e_002")` annotation as an explicit override.

### 5.6 Deterministic edge ids

```python
def make_edge_id(repo_id: str, pair_id: str, file: str, line: int, target_path: str) -> str:
    h = hashlib.sha1(f"{file}:{line}:{target_path}".encode()).hexdigest()[:12]
    return f"{repo_id}.{pair_id}.e_{h}"
```

Same input → same id, forever. Surviving renames is intentionally NOT a goal — a renamed file is a new edge by design (so impact analysis sees it).

### 5.7 Snapshot SHA

After all extraction completes:

```python
inputs = sorted([
    (repo.id, repo.sha) for repo in cfg.repos
] + [
    (pair.id, hash_file(pair.source.file), hash_file(pair.target.file)) for pair in cfg.pairs
] + [
    ("extractor_version", ATLAS_VERSION),
    ("tree_sitter_java_version", TS_JAVA_VERSION),
])
atlas_sha = sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
```

Same inputs → same `atlas_sha` → byte-identical SQLite. Used for snapshot pinning everywhere downstream.

### 5.8 Determinism rules

- Iterate files in `Path.glob` order then sort by `str(path).lower()`.
- Iterate tree-sitter matches in source-position order.
- All JSON written with `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)` and a trailing `\n`.
- SQLite inserts inside one transaction per `(repo, pair)`; `PRAGMA synchronous=FULL`.
- The whole DB is rebuilt from scratch on every full extract — no incremental drift.

### 5.9 Acceptance tests

| Test | Pass condition |
|---|---|
| Extract twice on same SHA | Byte-identical `atlas.db` |
| Inject a syntax error in one mapper | `atlas extract` exits non-zero, error names file + line |
| Run on `tiny-mapstruct` fixture | Produces a manifest matching the golden snapshot |
| Run on `tiny-multi-pair` fixture | Cross-pair composition works through `business_key` |

---

## 6. SQLite schema — the single source of truth

**File:** `~/.atlas/atlas.db` (configurable). Created and managed by `src/atlas/db.py`.

```sql
-- The snapshot anchor. Pin this SHA → reproducible queries forever.
CREATE TABLE snapshot (
    atlas_sha       TEXT PRIMARY KEY,
    built_at        TEXT NOT NULL,
    extractor_ver   TEXT NOT NULL,
    edge_count      INTEGER NOT NULL,
    mapper_count    INTEGER NOT NULL,
    field_count     INTEGER NOT NULL,
    test_count      INTEGER NOT NULL,
    invariants_json TEXT NOT NULL
);

CREATE TABLE repo (
    id              TEXT PRIMARY KEY,
    project         TEXT NOT NULL,
    branch          TEXT NOT NULL,
    sha             TEXT NOT NULL,
    browse_template TEXT NOT NULL
);

CREATE TABLE schema (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,        -- xsd | json-schema | proto | fixedlen | tagged
    file            TEXT NOT NULL
);

CREATE TABLE field (
    id              TEXT PRIMARY KEY,     -- "<schema_id>#<path>"
    schema_id       TEXT NOT NULL REFERENCES schema(id),
    path            TEXT NOT NULL,        -- dotted: "dbtr.acct.iban"
    business_key    TEXT,                 -- the cross-pair join key, e.g. "DebtorIBAN"
    type            TEXT,
    UNIQUE(schema_id, path)
);
CREATE INDEX idx_field_business_key ON field(business_key);

CREATE TABLE mapper (
    id              TEXT PRIMARY KEY,     -- fqn
    fqn             TEXT NOT NULL,
    kind            TEXT NOT NULL,        -- mapstruct-impl | builder | setter | fixedlen | tagged
    pair_id         TEXT NOT NULL,
    repo_id         TEXT NOT NULL REFERENCES repo(id),
    file            TEXT NOT NULL,
    sha             TEXT NOT NULL,
    browse_url      TEXT NOT NULL,
    scope_common    INTEGER NOT NULL DEFAULT 0,
    scope_country   TEXT,
    scope_clearing  TEXT,
    scope_product   TEXT,
    scope_field_group TEXT
);
CREATE INDEX idx_mapper_pair      ON mapper(pair_id);
CREATE INDEX idx_mapper_country   ON mapper(scope_country);
CREATE INDEX idx_mapper_clearing  ON mapper(scope_clearing);

-- THE ATOM. Every row carries full provenance.
CREATE TABLE edge (
    id                TEXT PRIMARY KEY,           -- repo.pair.e_<sha1[:12]>
    pair_id           TEXT NOT NULL,
    mapper_id         TEXT NOT NULL REFERENCES mapper(id),
    source_field_id   TEXT REFERENCES field(id),  -- nullable for constants
    target_field_id   TEXT NOT NULL REFERENCES field(id),
    kind              TEXT NOT NULL,              -- rename | constant | expression | format | concat | split | enrichment | lookup
    expression        TEXT NOT NULL,              -- the source-text RHS, verbatim
    static_helper_fqn TEXT,
    format_spec_json  TEXT,                       -- { offset, length, tag } for fixedlen/tagged
    file              TEXT NOT NULL,
    line              INTEGER NOT NULL,
    sha               TEXT NOT NULL,
    browse_url        TEXT NOT NULL
);
CREATE INDEX idx_edge_source ON edge(source_field_id);
CREATE INDEX idx_edge_target ON edge(target_field_id);
CREATE INDEX idx_edge_mapper ON edge(mapper_id);
CREATE INDEX idx_edge_pair   ON edge(pair_id);

CREATE TABLE test (
    id              TEXT PRIMARY KEY,             -- fqn
    fqn             TEXT NOT NULL,
    file            TEXT NOT NULL,
    line            INTEGER NOT NULL,
    sha             TEXT NOT NULL,
    browse_url      TEXT NOT NULL
);

CREATE TABLE edge_test (
    edge_id         TEXT NOT NULL REFERENCES edge(id),
    test_id         TEXT NOT NULL REFERENCES test(id),
    PRIMARY KEY (edge_id, test_id)
);

-- Build gate. Non-empty unparseable_json fails the extract.
CREATE TABLE coverage (
    repo_id           TEXT NOT NULL,
    pair_id           TEXT NOT NULL,
    files_scanned     INTEGER NOT NULL,
    mappers_detected  INTEGER NOT NULL,
    edges_emitted     INTEGER NOT NULL,
    unparseable_json  TEXT NOT NULL,              -- JSON array; non-empty = fail
    PRIMARY KEY (repo_id, pair_id)
);

-- Full-text search for the human UI.
CREATE VIRTUAL TABLE field_fts  USING fts5(field_id UNINDEXED, schema, path, business_key, type);
CREATE VIRTUAL TABLE mapper_fts USING fts5(mapper_id UNINDEXED, fqn, scope_text);
```

### 6.1 Cross-pair composition by SQL

This is how multi-service traceability falls out for free:

```sql
-- "MT103 50K → fraud account.iban": all hops, ordered.
WITH RECURSIVE path(edge_id, depth, hops) AS (
  SELECT e.id, 0, json_array(json_object('edge_id', e.id, 'mapper', e.mapper_id, 'browse', e.browse_url))
  FROM edge e
  JOIN field f ON e.source_field_id = f.id
  WHERE f.path = 'field_50K' AND f.schema_id = 'SWIFT_MT103.xsd'

  UNION ALL

  SELECT e2.id, p.depth + 1,
         json_insert(p.hops, '$[#]', json_object('edge_id', e2.id, 'mapper', e2.mapper_id, 'browse', e2.browse_url))
  FROM path p
  JOIN edge e1   ON p.edge_id = e1.id
  JOIN field tf  ON e1.target_field_id = tf.id
  JOIN field sf  ON tf.business_key = sf.business_key AND sf.id != tf.id
  JOIN edge e2   ON e2.source_field_id = sf.id
  WHERE p.depth < 6
)
SELECT * FROM path ORDER BY depth;
```

`business_key` on `field` is the join column. Schemas declare it via `x-atlas-business-key: DebtorIBAN`; `src/atlas/schemas.py` reads the declarations at extract time. Composition is *just* a recursive CTE — no separate engine, no graph DB.

---

## 7. Renderer — SQLite to Markdown site

**File:** `src/atlas/render.py`
**Invocation:** `atlas render --config atlas.yml --out ~/.atlas/site`

For every mapper row, write `<MapperName>.md` from a Jinja2 template:

```markdown
---
atlas_sha: {{ snapshot.atlas_sha }}
mapper_id: {{ mapper.id }}
mapper_kind: {{ mapper.kind }}
pair_id: {{ mapper.pair_id }}
repo: {{ mapper.repo_id }}
sha: {{ mapper.sha }}
file: {{ mapper.file }}
browse_url: {{ mapper.browse_url }}
scope: { common: {{ mapper.scope_common }}, country: {{ mapper.scope_country }}, clearing: {{ mapper.scope_clearing }}, product: {{ mapper.scope_product }} }
edges_count: {{ edges|length }}
tests_count: {{ tests|length }}
---

# {{ mapper.fqn.split('.')[-1] }}

`{{ mapper.fqn }}` — {{ mapper.kind }} mapper.

## Field-level edges

| edge_id | source | → | target | kind | expression | tests | code |
|---|---|---|---|---|---|---|---|
{% for e in edges %}
| `{{ e.id }}` | `{{ e.source_path or "(constant)" }}` | → | `{{ e.target_path }}` | {{ e.kind }} | `{{ e.expression|truncate(60) }}` | {{ e.test_count }} | [L{{ e.line }}]({{ e.browse_url }}) |
{% endfor %}

## Tests

{% for t in tests %}
- `{{ t.fqn }}` — covers {{ t.edge_count }} edges ([L{{ t.line }}]({{ t.browse_url }}))
{% endfor %}

## Cross-pair links

{% for link in cross_pair_links %}
- `{{ link.source_edge }}` → continues into pair `{{ link.next_pair }}` ([{{ link.next_mapper_short }}]({{ link.next_mapper_md }}))
{% endfor %}
```

Also emits:

- `site/projects/<project>/services/<svc>/graph.jsonld` — JSON-LD using `schemas/jsonld-context.json` (same content as SQLite, RDF-flavored).
- `site/projects/<project>/atlas-global.jsonld` — global graph.
- `site/snapshot.json` — `{ atlas_sha, built_at, counts }`.

The site is plain Markdown + JSON. Browseable with any static-site generator (we use Docusaurus or Astro Starlight; pick one in week 2). The React UI in §11 is the *interactive* layer; the Markdown site is the *archival* layer.

---

## 8. MCP server + REST shim + Bitbucket helpers

**File:** `src/atlas/mcp_server.py`
**Stack:** `mcp` (official Anthropic Python SDK) + FastAPI + `uvicorn` + `httpx` (for Bitbucket).
**Storage:** opens `atlas.db` read-only at the configured snapshot SHA.

### 8.1 Standard envelope

Every tool returns:

```python
class Meta(BaseModel):
    count: int
    complete: bool
    next_cursor: str | None
    atlas_sha: str
    query_hash: str
    invariants_checked: list[str]

class ProvenanceRecord(BaseModel):
    atom_id: str
    repo: str
    sha: str
    file: str
    line: int
    browse_url: str

class Envelope(BaseModel, Generic[T]):
    data: list[T]
    meta: Meta
    provenance: list[ProvenanceRecord]
```

### 8.2 Tool surface

Atlas tools (read-only, deterministic):

| Tool | Purpose |
|---|---|
| `pin_atlas_sha(sha)` | Lock subsequent calls in this session |
| `find_field(query, limit?, cursor?)` | FTS over `field_fts` |
| `get_field(field_id)` | Field detail |
| `find_mapper(query, scope?, limit?, cursor?)` | FTS over `mapper_fts` |
| `get_mapper(mapper_id)` | Mapper detail with all edges |
| `get_edge(edge_id)` | Edge detail |
| `trace_lineage(source?, target?, direction, scope?, max_depth?)` | The recursive CTE in §6.1 |
| `compare_models(left_schema, right_schema, scope?)` | Side-by-side mapping comparison |
| `mappers_by_country(country, pair?)` | Filtered list |
| `mappers_by_clearing(clearing, pair?)` | Filtered list |
| `mappers_by_product(product)` | Filtered list |
| `tests_for_edges(edge_ids[])` | Coverage lookup |
| `gaps(scope?, kind?)` | Coverage gap explorer |
| `impact_of_change(change_spec)` | The big one — see §8.4 |
| `diff_versions(sha_a, sha_b, scope?)` | Snapshot diff |
| `verify_edges(edge_ids[])` | Round-trip sanity check (used by validator) |
| `snapshot_info()` | Counts + invariants |

Bitbucket tools (read + gated write):

| Tool | Purpose |
|---|---|
| `bb.read_file(repo, sha, file, line_from?, line_to?)` | Exact bytes from Bitbucket REST at SHA |
| `bb.diff(repo, sha_a, sha_b, file?)` | Typed diff hunks |
| `bb.pr_for_sha(repo, sha)` | PR metadata |
| `bb.create_pr(...)` | **Gated** — requires validator-approved change_plan_id |
| `bb.commit_files(...)` | **Gated** — same gate |

### 8.3 REST shim for the UI

Same handlers, exposed twice. FastAPI routes auto-generated from the MCP tool registry:

```python
# src/atlas/mcp_server.py — sketch
from mcp.server.fastmcp import FastMCP
from fastapi import FastAPI

mcp = FastMCP("atlas")
api = FastAPI()

@mcp.tool()
async def find_field(query: str, limit: int = 50, cursor: str | None = None) -> Envelope[FieldNode]:
    ...

# Auto-register every @mcp.tool as GET /api/v1/<tool_name>
register_rest(mcp, api, prefix="/api/v1")

# Mount MCP transport at /mcp
api.mount("/mcp", mcp.streamable_http_app())

# Run with: uvicorn atlas.mcp_server:api --port 4281
```

The UI (§11) talks to `/api/v1/*`. The agent (later) talks to `/mcp`. Same handlers, same envelopes, same SQLite.

### 8.4 `impact_of_change` algorithm

```
1. Resolve target field(s) implied by ChangeSpec (rename | drop | type_change | format_change | add).
2. BFS downstream over edges where source_field == target field, applying scope filter at each hop.
3. BFS upstream symmetrically.
4. For each visited edge, collect: mapper, service, scope, test coverage.
5. Topo-sort affected services using cross-pair dependency graph.
6. Compute coverage gaps among affected edges.
7. Build Bitbucket diff URLs for every affected file at HEAD.
8. Return ImpactReport with per-edge provenance.
```

Output:

```python
class ImpactReport(BaseModel):
    change: ChangeSpec
    affected_edges: list[str]
    affected_mappers: list[str]
    affected_services: list[ServiceImpact]
    affected_clearings: list[str]
    affected_countries: list[str]
    coverage_gaps: list[GapEntry]
    rollout_order: list[str]
    bitbucket_previews: list[BitbucketPreview]
    generated_at: str
    atlas_sha: str
```

### 8.5 Determinism

- All reads inside `BEGIN IMMEDIATE` SQLite transactions on a read-only snapshot.
- Same `(atlas_sha, tool, args)` → byte-identical response.
- Snapshot updates: aggregator builds a shadow `.db.new`, validates invariants, atomic `os.rename` to `atlas.db`. Live queries finish on the old snapshot.

---

## 9. Validator — 30 lines

**File:** `src/atlas/validate.py`

```python
import re

ATOM_PATTERNS = {
    "edge_id":     re.compile(r"\b[a-z0-9-]+\.[a-z0-9_]+\.e_[0-9a-f]{12}\b"),
    "mapper_fqn":  re.compile(r"\b(?:[a-z][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_]+\b"),
    "file_path":   re.compile(r"\b(?:[\w-]+/)+[\w.-]+\.(?:java|json|xsd|yaml|md)\b"),
    "url":         re.compile(r"\bhttps?://\S+\b"),
    "sha":         re.compile(r"\b[0-9a-f]{7,40}\b"),
    "field_path":  re.compile(r"`([a-zA-Z_][\w.]*)`"),
}

def collect_seen(transcript: list[dict]) -> dict[str, set[str]]:
    seen = {k: set() for k in ATOM_PATTERNS}
    for call in transcript:
        text = json.dumps(call.get("response", ""), default=str)
        for kind, pat in ATOM_PATTERNS.items():
            for m in pat.finditer(text):
                seen[kind].add(m.group(0) if kind != "field_path" else m.group(1))
    return seen

def validate(draft: str, transcript: list[dict]) -> ValidationResult:
    seen = collect_seen(transcript)
    unverifiable = []
    for kind, pat in ATOM_PATTERNS.items():
        for m in pat.finditer(draft):
            atom = m.group(0) if kind != "field_path" else m.group(1)
            if atom not in seen[kind]:
                unverifiable.append({"atom": atom, "kind": kind, "offset": m.start()})
    return ValidationResult(ok=not unverifiable, unverifiable=unverifiable)
```

Invoked by:

- The UI before "Generate Jira" / "Generate PRs" — blocks the action if any atom is unverifiable.
- A CI hook on agent-authored PRs — rejects PRs whose body or title contains atoms missing from the corresponding MCP transcript (captured automatically).

### 9.1 Adversarial test suite

`tests/adversarial/` contains 50+ pairs of (draft, transcript) where drafts contain planted fabrications. The validator must flag every fabrication. Zero false negatives. False positives allowed but logged.

---

## 10. Auto-learning — one cron line

**File:** `src/atlas/scheduler.py` (optional process) **or** plain cron.

### 10.1 Pull mode (always-on safety net)

```cron
# Daily incremental
0 3 * * * cd /opt/atlas && for repo in repos/*/; do git -C "$repo" pull --quiet; done && uv run atlas extract --config atlas.yml && uv run atlas render --config atlas.yml

# Weekly full rebuild
0 2 * * 0 cd /opt/atlas && for repo in repos/*/; do git -C "$repo" fetch --all --prune && git -C "$repo" reset --hard origin/main; done && uv run atlas extract --config atlas.yml --full && uv run atlas render --config atlas.yml
```

### 10.2 Push mode (faster, pipeline-driven)

Each tracked repo's Bitbucket pipeline calls:

```bash
curl -X POST https://atlas.x.internal/api/v1/repository_dispatch \
     -H "Authorization: Bearer $ATLAS_PUSH_TOKEN" \
     -d '{"repo_id": "payment-service", "sha": "'"$BITBUCKET_COMMIT"'"}'
```

The MCP server (which also exposes this REST endpoint) enqueues an extract-just-this-repo task. End-to-end latency from merge to fresh `atlas.db`: <10 minutes on a real codebase.

### 10.3 Both modes coexist

Push for speed, pull for safety. Pull catches anything push missed. State lives in `~/.atlas/scheduler-state.json` but is not authoritative — a full rescan ignores it.

### 10.4 Notifications

After every successful `extract + render`, post a Slack summary if `SLACK_WEBHOOK_ATLAS` is set: snapshot SHA, edge delta, coverage delta, link to the rendered site.

---

## 11. Web UI

**Package:** `ui/`
**Stack:** React 19 + TypeScript + Vite + TanStack Router + TanStack Query + Tailwind v4 + shadcn/ui primitives (custom-themed) + D3-sankey + `unified`/`rehype` for Markdown rendering.

### 11.1 Aesthetic — committed, non-negotiable

**Editorial-dark, terminal-grade.** Linear × Stripe Press × Bloomberg Terminal. This is a precision instrument, not a SaaS dashboard.

- **Type.** Display + body: **Söhne** (Klim) or, if licensing isn't available, **Geist Sans**. Mono: **JetBrains Mono** or **IBM Plex Mono**. Pick one of each and commit. **Banned:** Inter (default), Roboto, Arial, system-ui.
- **Color.** Background `#0B0C0E`. Surface `#14161A`. Border `#22262C`. Text primary `#E8E6E1`. Text secondary `#9AA0A6`. Single accent `#E8B96A` (warm amber). Semantic: success `#7FB069`, danger `#D9534F`, warn `#E8B96A`. **No purple gradients.**
- **Spacing.** 4px base unit. Generous gutters (24px), tight rows (8px). Editorial 12-col grid, content blocks frequently break to 5/7 asymmetry for emphasis.
- **Motion.** Reserved. Sankey bands fade-in 60ms staggered. Filter changes 120ms cross-fade. Hover 80ms. Nothing bounces.
- **Density.** 50+ rows per table without crowding. Mono for ids, sans for prose. Right-align numerics. Single-pixel borders, never double.
- **The signature element: the provenance bar.** A footer that pins on every page: `atlas_sha`, edge count, last-built timestamp, link to the audit drawer (last 100 MCP calls). One click reveals the exact MCP queries that built the page.

### 11.2 Routes

```
/                                   → Overview + project picker
/projects/:p                         → Project dashboard
/projects/:p/services                → Service list
/projects/:p/services/:svc           → Service detail (mappers list)
/projects/:p/mappers/:m              → Mapper page (renders <MapperName>.md)
/projects/:p/fields                  → Field search (the global search)
/projects/:p/fields/:fid             → Field detail (sources, targets, mappers touching)
/projects/:p/lineage                 → Sankey lineage (with filter bar)
/projects/:p/compare                 → Domain-model comparison
/projects/:p/impact                  → Impact analysis (the headline page)
/projects/:p/gaps                    → Coverage gap explorer
/projects/:p/diff/:a/:b              → Snapshot diff
/audit                               → Last 100 MCP calls
```

### 11.3 The five surfaces

Same as the original spec — kept verbatim because the UI is exactly the same product:

1. **Field search** — single input, autofocus, debounced FTS. `Enter` → field detail.
2. **Field detail** — three columns: sources, targets, mappers touching. Coverage strip up top.
3. **Sankey lineage** — D3 Sankey across service columns, filterable by country/clearing/product/pair. Band thickness = edge count.
4. **Domain-model comparison** — left-vs-right pickers, color-coded mapping rows (green/amber/red/gray).
5. **Impact analysis** — form on top, dashboard below: blast radius KPIs, services tree, coverage gaps, suggested rollout order, Bitbucket previews, action buttons (Generate Jira / Generate PRs / Export).

### 11.4 Provenance affordances

- Every numeric cell is hover-attributable: tooltip shows the exact MCP query and result count.
- Every name (mapper / field / edge) is one click from Bitbucket at sha+file+line.
- Every page URL is sha-pinned (`?atlas_sha=abc123`). Sharing the URL guarantees identical view forever.
- Audit drawer accessible from any page (`cmd+shift+a`).

### 11.5 The UI never composes prose

All textual descriptions of mappers/edges come from rendered Markdown files (sanitized via `unified` + `rehype` → React components). The UI is a **renderer**, not an author. This prevents the UI from drifting away from atlas.db truth.

---

## 12. Testing strategy

### 12.1 Test layers

| Layer | Tooling | What |
|---|---|---|
| Unit | `pytest` | Per-classifier rules, scope inference, path normalisation, edge-id determinism |
| Property | `hypothesis` | Determinism: extract twice → byte-identical SQLite; round-trip Markdown render |
| Golden | `pytest` + git-tracked fixtures | `tiny-mapstruct`, `tiny-fixedlen`, `tiny-builder`, `tiny-multi-pair`, `tiny-broken` |
| Contract | `pytest` + `jsonschema` | Every MCP envelope validates |
| Integration | `pytest` + `playwright` | extract → render → MCP → UI flow |
| Adversarial | `pytest` | Validator's 50+ planted-fabrication suite |

### 12.2 Golden fixtures (must exist before merging extractor)

`examples/fixtures/`:

- `tiny-mapstruct/` — 2 mappers, 7 edges, fully MapStruct.
- `tiny-fixedlen/` — 1 encoder, 12 edges, sanctions-style.
- `tiny-builder/` — 1 builder mapper, 5 edges.
- `tiny-multi-pair/` — 3 pairs sharing a junction field. Validates `business_key` cross-pair composition.
- `tiny-broken/` — 1 syntax-error file. Asserts the build fails loudly.

### 12.3 Continuous accuracy CI job

`.github/workflows/accuracy.yml`: on every PR, run determinism + golden + contract + adversarial. **Merge blocked** unless all pass.

---

## 13. Two-week build plan

| Day | Milestone | Exit criterion |
|---|---|---|
| 1 | `atlas-config` + JSON schema + auto-detection | `atlas validate-config` passes on `examples/atlas.yml` |
| 2 | DB schema + migrations | `atlas init` creates a clean `atlas.db` |
| 3 | Schema parsers (XSD / JSON / Proto / fixedlen / tagged) | All five fixtures' source/target schemas parse |
| 4-5 | Extractor: tree-sitter setup + setter/mapstruct-impl path | `tiny-mapstruct` golden passes byte-identically twice |
| 6 | Extractor: builder + fixedlen + tagged + tests + cross-pair | Remaining four fixtures pass; build fails on `tiny-broken` |
| 7 | Renderer (Markdown + JSON-LD + snapshot.json) | `~/.atlas/site/` built end-to-end |
| 8 | MCP server + REST shim (all §8.2 tools) | All tools contract-tested |
| 9 | Bitbucket helpers + validator + adversarial suite | Adversarial suite green |
| 10 | Auto-learning (push + pull) + Slack notify | Synthetic merge → fresh DB <10min |
| 11-12 | UI: search, field detail, mapper page, audit drawer | Lighthouse ≥95, sub-500ms search |
| 13 | UI: Sankey, comparison, impact dashboard | All five surfaces ship; provenance bar everywhere |
| 14 | End-to-end on three real services | Real `atlas.db` in production; demo to senior management |

The agent module starts after Day 14 and follows its own plan once requirements are concrete. See `docs/AGENT_INTEGRATION_TODO.md`.

---

## 14. Worked example — full end-to-end trace

The user asks: *"How does SWIFT MT103 field 50K end up in the fraud system's `account.iban`?"*

Atlas answers via three SQL queries (one per pair) joined by `business_key`, returning a path with full provenance:

```json
{
  "data": [{
    "path": [
      {
        "edge_id": "payment-service.mt103_to_local.e_3a7f12c9b4d8",
        "mapper": "com.x.payment.mapper.common.SwiftMt103ToLocalDomainMapper",
        "source": { "schema": "SWIFT_MT103.xsd", "path": "field_50K" },
        "target": { "schema": "LocalDomain.json", "path": "dbtr.acct.iban", "business_key": "DebtorIBAN" },
        "kind": "rename",
        "expression": "src.getField50K().substring(0, 34)",
        "browse_url": "https://bitbucket.x.com/projects/PMT/repos/payment-service/browse/payment-transform/.../SwiftMt103ToLocalDomainMapper.java?at=a1b2c3d#142"
      },
      {
        "edge_id": "sanctions-service.local_to_sanctions.e_7c2e88f4a1b3",
        "mapper": "com.x.sanctions.encoder.common.LocalDomainToSanctionsFixedLen",
        "source": { "schema": "LocalDomain.json", "path": "dbtr.acct.iban", "business_key": "DebtorIBAN" },
        "target": { "schema": "sanctions/spec.yaml", "path": "tag_5901", "business_key": "DebtorIBAN" },
        "kind": "format",
        "expression": "padRight(src.getDbtr().getAcct().getIban(), 34)",
        "browse_url": "https://bitbucket.x.com/projects/PMT/repos/sanctions-service/browse/.../LocalDomainToSanctionsFixedLen.java?at=f5e6789#88"
      },
      {
        "edge_id": "fraud-service.local_to_fraud.e_9d3a55c12e7f",
        "mapper": "com.x.fraud.mapper.LocalDomainToFraudJsonMapper",
        "source": { "schema": "LocalDomain.json", "path": "dbtr.acct.iban", "business_key": "DebtorIBAN" },
        "target": { "schema": "fraud/v3.json", "path": "account.iban", "business_key": "DebtorIBAN" },
        "kind": "rename",
        "expression": "src.getDbtr().getAcct().getIban()",
        "browse_url": "https://bitbucket.x.com/projects/PMT/repos/fraud-service/browse/.../LocalDomainToFraudJsonMapper.java?at=b8c4d12#56"
      }
    ]
  }],
  "meta": {
    "atlas_sha": "0xfacefeed...",
    "complete": true,
    "invariants_checked": ["snapshot_sealed", "checksum_ok"]
  },
  "provenance": [
    { "atom_id": "payment-service.mt103_to_local.e_3a7f12c9b4d8", "repo": "payment-service", "sha": "a1b2c3d", "file": "...", "line": 142, "browse_url": "..." },
    { "atom_id": "sanctions-service.local_to_sanctions.e_7c2e88f4a1b3", "repo": "sanctions-service", "sha": "f5e6789", "file": "...", "line": 88, "browse_url": "..." },
    { "atom_id": "fraud-service.local_to_fraud.e_9d3a55c12e7f", "repo": "fraud-service", "sha": "b8c4d12", "file": "...", "line": 56, "browse_url": "..." }
  ]
}
```

Click any `browse_url` → opens the exact line of the actual Java file at the actual SHA in Bitbucket. There is no path through Atlas where this provenance is missing or wrong, because the extractor wrote those tuples at the same time it read the Java source.

That's 100% end-to-end traceability. SQL + tree-sitter + a join column. No magic.

---

## 15. Claude Code kickoff prompt

Paste this verbatim into Claude Code on day 1:

> You are building **Atlas Lite**, a deterministic, hallucination-proof knowledge platform for cross-service mapping lineage with 100% end-to-end traceability. The full specification is in `ATLAS_LITE_SPEC.md` at the repo root. Read it end-to-end before writing any file.
>
> **Hard rules:**
> 1. Code is the only source of truth. The system extracts; it never invents.
> 2. Every output (DB row, Markdown file, MCP response, UI cell) carries `{repo, sha, file, line, browse_url}` provenance.
> 3. Determinism: same input → byte-identical output. Property-tested.
> 4. Fail-loud on unparseable input. Never silently skip.
> 5. The agent module is a placeholder. Other modules integrate against a stub now; the agent slots in later.
>
> **Stack:** Python 3.12 (uv) for back-end + extractor; React 19 + Vite + TypeScript for the UI. No Java code, no Maven plugin. Tree-sitter parses Java directly.
>
> **Build order:** follow §13 day-by-day. Do not skip ahead.
>
> **Skills to activate** (located in `/mnt/skills/public/` or `/mnt/skills/examples/`):
> - `mcp-builder` — when implementing the MCP server.
> - `frontend-design` — when starting the UI. The §11.1 aesthetic must not be diluted.
> - `theme-factory` — to generate the editorial-dark theme tokens.
> - `web-artifacts-builder` — for prototyping individual UI surfaces.
> - `doc-coauthoring` — keep `docs/` in lockstep with code.
>
> **First action:** create `pyproject.toml` (uv project), `src/atlas/config.py`, and `schemas/atlas-config.schema.json`. Write tests that load `examples/atlas.yml` and assert auto-detection produces deterministic stderr.
>
> **Definition of done per milestone:** the exit criterion in §13. CI must pass `accuracy.yml` (§12.3) before merging any milestone.
>
> **Style:** match §11.1 verbatim. Editorial-dark, terminal-grade. Söhne or Geist + JetBrains Mono. No purple gradients. No SaaS slop.

### 15.1 If the spec is ambiguous

Open `docs/QUESTIONS.md`, write the ambiguity, pick the simpler interpretation, document the call. Do not block the build.

### 15.2 What success looks like

- `uv run atlas extract` runs against the user's local repos and produces a deterministic `atlas.db`.
- `uv run atlas render` produces a Markdown site with full provenance.
- `uv run atlas serve` answers all §8.2 tools at `/api/v1/*` and `/mcp`.
- `pnpm dev` (in `ui/`) shows the five surfaces in §11.3, all sha-pinned.
- A daily cron line keeps `atlas.db` fresh against tracked branches.
- The validator catches every adversarial fabrication.
- One YAML file (`atlas.yml`) reconfigures everything.

When all of the above are true, **Atlas Lite is done**. The agent module follows.

---

**End of spec.** Next file Claude Code should create: `examples/atlas.yml` mirroring §4 verbatim.
