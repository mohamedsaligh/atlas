# atlas-lite — Design + Roadmap

**Date:** 2026-05-08
**Branch:** `develop`
**Latest commit:** `73f66a7` — N-deep resolver chain via path-prefix bindings

This is the load-bearing planning document for atlas-lite. It records what
ships today, the data-model invariants, the resolver-chain semantics, and the
ordered roadmap to the user's full original ask (impact analysis, E2E mapping
view, Obsidian-style graph, enterprise production grade).

---

## 1. North star (the original ask)

1. **Field-level lineage at 100% honest coverage** for the multi-service Maven
   payments codebase (~30 microservices, MapStruct + builder + plain Java).
2. **Impact analysis**: "if I change field X, what breaks?" — pulled by
   country / clearing / product / field with deterministic blast radius.
3. **E2E mapping view (UI)**: clean, professional, country → clearing →
   product → mapper → field, full or partial drill-down.
4. **Graph view**: Obsidian-style fluid force-directed graph connecting
   field nodes across product/clearing/country at scale (~50k+ edges).
5. **Enterprise production-grade**: deterministic output, audit trail per
   edge, schema validation, CI hardening, semver, container build, SBOM,
   SSO/OIDC for read APIs.

---

## 2. Status snapshot

| Pillar | State | Notes |
|---|---|---|
| Java extractor (atlas-java, Maven plugin) | ✅ shipped | Production-tested on the real codebase. Text-regex `MapStructFastImplExtractor` after JavaSymbolSolver hangs were ruled out. |
| Python extractor (atlas-lite, tree-sitter) | ✅ shipped | The active runtime. Sub-second on small fixtures; minutes on the full real codebase. |
| Resolver chain (direct → wrapper-arg → qualifier → static-helper → intra-class → ternary/cast/paren) | ✅ shipped | Bounded depth, cycle-checked, with per-edge audit trail. |
| Buckets A/B/C/D long-tail closers | ✅ shipped (commit `9a18650`) | construction kind, inheritance walk for qualifier field types, local-var init chasing, ternary unwrapping. |
| Entry-point as first-class | ✅ shipped (commit `8b3c666`) | `entry_point` table + `edge.entry_point_id` FK. The unit a BA reasons about. |
| Helper-body capture | ✅ shipped (commit `8b3c666`) | `helper` table, FQN-deduped, full body verbatim with start/end line anchors. |
| `static_helper_fqn` on qualifier kind | ✅ shipped (commit `8b3c666`) | Back-filled from the resolution trail. Direct joins without going through `edge_resolution`. |
| **N-deep path-prefix bindings** | ✅ shipped (commit `73f66a7`) | Helper params now inherit the caller's source root + accumulated path. Closes the gap where qualifier→static→`param.getX().getY()` resolved to `_(constant)_`. |
| Coverage % denominator | ⏳ commit 3 | `unmatchedTargetFields` against the target schema. Both JSON Schema and `kind: java-class` supported. |
| Impact CLI (`atlas impact <field>`) | ⏳ commit 3 | Reverse-edge BFS, output grouped by country/clearing/product/entry-point. |
| BA-grade Markdown render | ⏳ commit 2 | Per-entry-point `.md` with helper bodies inlined under each qualifier/static_call edge. |
| REST API (FastAPI) + OpenAPI | ⏳ Phase 2 | Substrate for UI + graph; OpenAPI is the contract; CI hardens here. |
| E2E table UI (React + Tailwind) | ⏳ Phase 3 | Country → clearing → product → entry-point → field, filterable. Builds on REST. |
| Obsidian-style graph (WebGL) | ⏳ Phase 3 | `react-force-graph-3d` (Three.js) at ~50k-edge scale. Hardest piece. |
| CI hardening (lint + mypy + pytest --cov ≥80%) | ⏳ Phase 2 | Bundled with REST + container build + SBOM. |

**Test count today:** 5/5 passing (`tests/test_extract.py`).

---

## 3. Data model

Single source of truth: SQLite at `cfg.storage.db_path` (default `~/.atlas/*.db`).

### 3.1 Table summary

| Table | Purpose | Primary key |
|---|---|---|
| `snapshot` | Atlas-SHA, build time, version, totals | `atlas_sha` |
| `repo` | Configured repos (id, branch, sha, browse template) | `id` |
| `schema` | Source / target schemas referenced by pairs | `id` (basename of the schema file) |
| `field` | Every leaf field enumerated from a schema | `schema_id#path` |
| `mapper` | One row per mapper class that emitted edges | `mapper_id` (class FQN) |
| **`entry_point`** | One row per top-level transformation method (the BA-facing unit) | `repo.pair.ep_<sha1>` |
| **`helper`** | Helper method bodies, deduped by FQN | `fqn` |
| `edge` | One row per field-level mapping (target ← source) | `repo.pair.e_<sha1>` |
| `edge_resolution` | Per-edge resolution trail — every hop the resolver walked | `(edge_id, seq)` |
| `edge_test` | Edge ↔ unit test links (future use) | `(edge_id, test_id)` |
| `coverage` | Per-(repo, pair) extraction stats + unmatched JSON | `(repo_id, pair_id)` |
| `field_fts`, `mapper_fts` | FTS5 search indexes | virtual |

### 3.2 Key columns

**`entry_point`** — pivots Markdown, coverage, impact, UI, graph onto methods:
- `class_fqn`, `method_name`, `method_signature` — full signature line.
- `source_schema_ids` (JSON array), `target_schema_id` — what domains it spans.
- `scope_country`, `scope_clearing`, `scope_product`, `scope_field_group` —
  flattened from `mapper.scope` for fast filter.
- `edge_count` — pre-aggregated.
- `resolution_percent` — fraction of this EP's own edges where the
  resolver landed on a real source schema path (`source_field_id IS NOT
  NULL`). Answers "did the resolver succeed for the fields this method
  writes?". *Not* the same as pair-level `coverage_percent` (a narrow
  EP that resolves all 5 of its 5 edges is 100% here, even if the
  pair's target schema has 1000 leaves).

**`helper`** — BA-readable proof:
- `fqn`, `file`, `start_line`, `end_line` — line-anchored to the source.
- `signature` — declaration line (modifiers + return + name + params).
- `body` — full verbatim Java text. Markdown render inlines this.
- `body_sha256` — change detection.

**`edge`** — denormalized for direct joins:
- `entry_point_id` FK — joins to `entry_point`.
- `static_helper_fqn` — populated on `kind ∈ (qualifier, static_call, intra_class)`
  by back-filling from the trail's last helper hop. No more NULLs on qualifier kind.
- `kind` ∈ `{rename, constant, format, expression, concat, qualifier, static_call,
  enrichment, construction, unmapped}`.

**`edge_resolution`** — full trail per edge:
- `seq` 0-indexed in walk order.
- `kind` ∈ `{direct, wrapper_arg, qualifier, static_call, intra_class}`.
- `helper_fqn` — populated when the step walked into a helper.

---

## 4. Resolver chain (the load-bearing logic)

### 4.1 Pipeline (deterministic, first match wins)

For every `target.setX(rhs)`, the resolver tries in order:

1. **Direct getter chain** — `param.getY().getZ()` → `kind=rename`.
2. **Qualifier body recursion** — instance method on a configured class
   (`resolvers.qualifier_classes`, glob-matched) → walk return, then setter
   chain on a target var inside the helper.
3. **Static-helper body recursion** — call on an `UpperCase` receiver whose
   FQN matches `resolvers.static_helper_classes` → walk helper body.
4. **Intra-class helper recursion** — bare `helperName(args)` resolving to a
   sibling method in the enclosing class.
5. **Wrapper-arg recursion** — try each argument in turn.
6. **Conditional / cast / paren** — unwrap and retry.
7. **Local-var init chasing** (Bucket C) — bare identifier whose initialiser
   traces back to a known parameter.
8. **Unmatched** — `kind=expression`, `source=null`. Counted in coverage.

Bounded by `cfg.max_depth` (default 5). A `visited` set prevents cycles.

### 4.2 Path-prefix invariant (commit `73f66a7`)

`ParamBinding` carries `path_prefix: str` — the path the caller already walked
before this binding entered scope. When a helper is invoked with
`helper(parent.getChild().getGrand())`, the helper's parameter is aliased to
the *caller's* root binding with `path_prefix="child.grand"`. Inside the
helper body, `param.getX()` lands on `(root_binding, "child.grand.x")` — not
on a fresh unbound type.

This is what makes N-deep `qualifier → static → param.getX().getY()` chains
traceable end-to-end. The `tiny-multihop` fixture (and its unit test) proves
this end-to-end.

### 4.3 Trail semantics

Each helper hop appends a `Resolution` step to `edge.trail`. Persist writes
each step to `edge_resolution`. The trail is the audit proof that the
recovered source path is real and traceable. Markdown render walks the trail
top-to-bottom and inlines each helper body.

---

## 5. Configuration (`atlas.yml`)

Required for production extraction:

```yaml
version: 1

repos:
  - id: <service-id>
    path: <local-or-mounted-path>
    project: <project-key>
    branch: main

pairs:
  - id: <pair-id>
    sources:
      - { name: <Source>, file: <abs-or-rel>.json, kind: json-schema, type_fqns: ["<source.fqn>"] }
    targets:
      - { name: <Target>, file: <abs-or-rel>.json, kind: json-schema, type_fqns: ["<target.fqn>"] }
    scan_globs:
      - "<service-dir>/<module>/src/main/java/**/mapper/**/*.java"
    resolvers:
      qualifier_classes:
        - "<root>.qualifier.*"             # glob; broad coverage
      static_helper_classes:
        - "<root>.qualifier.*"             # if utils live next to qualifiers
        - "<root>.util.*"                  # general util namespace
        - "<root>.mapper.helper.*"         # any helper sub-tree
      max_depth: 5
      follow_intra_class: true
    scope_rules:
      - glob: "<service>/<module>/src/main/java/**/{country}/{clearing}/**"
        scope: { layer: country }
      - filename_pattern: "^(?P<country>[A-Z]{2})(?P<clearing>[A-Za-z]+)Mapper.*\\.java$"
        scope: { layer: clearing }

storage:
  db_path: ~/.atlas/<service-id>.db
  site_path: ~/.atlas/<service-id>-site
  cache_path: ~/.atlas/<service-id>-cache
```

**Critical:** `static_helper_classes` is the lever for closing the long tail.
Every util namespace your qualifiers delegate into must be listed. Use globs
generously; the resolver's `visited` set + `max_depth` make over-inclusion
safe.

---

## 6. Verification recipes

After every extract, run these queries against the DB to validate behavior.

### 6.1 Sanity checks (must always pass)

```sql
-- New tables exist and populate
SELECT COUNT(*) AS entry_points FROM entry_point;
SELECT COUNT(*) AS helpers      FROM helper;
SELECT COUNT(*) AS edges        FROM edge;

-- Every edge has an entry_point_id (no orphans)
SELECT COUNT(*) AS orphan_edges FROM edge WHERE entry_point_id IS NULL;
-- expected: 0

-- static_helper_fqn now populated on every qualifier / static_call edge
SELECT
  kind,
  COUNT(*)                                                 AS total,
  SUM(CASE WHEN static_helper_fqn IS NULL THEN 1 ELSE 0 END) AS missing_fqn
FROM edge
WHERE kind IN ('qualifier', 'static_call', 'intra_class')
GROUP BY kind;
-- expected: missing_fqn = 0 for every row
```

### 6.2 Top entry points (BA-facing unit)

```sql
SELECT class_fqn, method_name, edge_count, target_schema_id
FROM entry_point
ORDER BY edge_count DESC
LIMIT 20;
```

### 6.3 Helper-body capture (BA-readable proof)

```sql
-- Spot-check: full body verbatim for a known qualifier
SELECT signature, start_line, end_line, body
FROM helper
WHERE fqn LIKE '%QualifierDefinitions%'
LIMIT 3;

-- Helper bodies sized — sanity that they're not truncated
SELECT MIN(LENGTH(body)), AVG(LENGTH(body)), MAX(LENGTH(body)) FROM helper;
```

### 6.4 N-deep resolution (commit `73f66a7` validation)

```sql
-- Edges with >= 2 hops in the trail (qualifier → static, etc.)
SELECT er.edge_id, GROUP_CONCAT(er.kind, ' → ' ORDER BY er.seq) AS chain
FROM edge_resolution er
GROUP BY er.edge_id
HAVING COUNT(*) >= 2
ORDER BY edge_id
LIMIT 20;

-- After adding a util class to static_helper_classes, the count of
-- qualifier-kind edges with a real source path should rise:
SELECT
  COUNT(*)                                                  AS qualifier_total,
  SUM(CASE WHEN source_field_id IS NOT NULL THEN 1 ELSE 0 END) AS resolved,
  ROUND(100.0 * SUM(CASE WHEN source_field_id IS NOT NULL THEN 1 ELSE 0 END)
        / COUNT(*), 1)                                       AS resolved_pct
FROM edge
WHERE kind = 'qualifier';
```

### 6.5 Resolver-chain visibility — what helpers are referenced most

```sql
SELECT static_helper_fqn, COUNT(*) AS uses
FROM edge
WHERE static_helper_fqn IS NOT NULL
GROUP BY static_helper_fqn
ORDER BY uses DESC
LIMIT 30;
```

Helpers that appear here but **not** in the `helper` table are unconfigured
candidates — add their parent class glob to `resolvers.static_helper_classes`
to recover the next layer of source paths.

### 6.6 Per-entry-point edge breakdown (BA's view)

```sql
SELECT ep.class_fqn, ep.method_name, e.kind, COUNT(*) AS n
FROM edge e
JOIN entry_point ep ON e.entry_point_id = ep.id
GROUP BY ep.id, e.kind
ORDER BY ep.id, n DESC;
```

### 6.7 Determinism gate

```bash
atlas extract -c atlas.yml --full
sqlite3 ~/.atlas/<service>.db "SELECT atlas_sha FROM snapshot"   # capture
atlas extract -c atlas.yml --full
sqlite3 ~/.atlas/<service>.db "SELECT atlas_sha FROM snapshot"   # must match
```

---

## 7. Roadmap (ordered, with deliverables and effort)

### Commit 2 — BA-grade Markdown render (next)

**Deliverable:** `atlas render` writes one `.md` per entry point under
`{site_path}/entry-points/{country}/{clearing}/{product}/{entry_point_id}.md`.

For each edge:
- target field path
- source field path (or `_unresolved_` with reason)
- kind tag
- expression (code anchor)
- if `kind ∈ (qualifier, static_call)`: the helper body inlined in a fenced
  Java block, line-anchored to source.
- cross-link to source schema, target schema, and any sibling entry points
  on the same target schema.

**Effort:** ~80 LOC (Jinja2 template + render module). Half a day.

**Verification:** open one `.md` per scope; confirm BA can read the full
helper logic without ever opening the IDE.

### Commit 3 — Coverage % + impact CLI

**Coverage:**
- Walk every target schema referenced by any pair, enumerate its leaves.
- Subtract paths actually written by edges.
- Populate `coverage.unmatched_json`; compute `coverage_percent` per (repo, pair).
- Populate `entry_point.coverage_percent` (per-entry-point).
- Emit synthetic `kind=unmapped` edges for unmatched fields (optional).
- Honor `x-atlas-business-key`, `x-atlas-ignore` annotations from the schema.

**Impact CLI:**
```bash
atlas impact --schema TransactionDetail --path dbtr.acct.iban
```
Output (grouped by scope):
- direct mappers (entry-points that write to this path)
- transitive impact (entry-points that consume schemas which contain this
  field at depth N)
- helpers that reference the path

Implementation: recursive CTE in SQLite over the `edge` table; reverse-index
on `target_field_id` and `source_field_id`.

**Effort:** ~150 LOC. ~1.5 days.

**Verification:**
- Coverage % matches manual count of leaves vs written paths on a small fixture.
- `atlas impact` on a known leaf returns the exact set of writers.

### Commit 4 — Drift gate (ship with commit 3)

```bash
atlas check --baseline coverage-baseline.json --max-added 0 --max-removed 5
```
Compares current coverage against a checked-in baseline; non-zero exit if
new unmatched fields appear or coverage drops below threshold. Wire into CI
as a gate.

### Phase 2 — REST API + OpenAPI + CI hardening

- FastAPI app reading SQLite (read-only).
- Endpoints (per ATLAS_SPEC §8.1 envelope):
  - `GET /find_field?schema=...&path=...`
  - `GET /trace_lineage?from=...&to=...`
  - `POST /compare_models`
  - `POST /impact_of_change`
- OpenAPI 3.1 spec generated; semver-versioned.
- Auth: SSO/OIDC bearer (provider TBD).
- CI: ruff + mypy --strict + pytest --cov ≥80% gate.
- Container: multi-stage, distroless or Wolfi base, non-root.
- SBOM: CycloneDX, generated at build.
- Effort: ~3 days for API + hardening.

### Phase 3 — UI + graph

**E2E table UI:**
- React 19 + Vite + Tailwind v4.
- Hierarchy: country → clearing → product → entry-point → edges.
- Filter chips (kind, scope, schema, helper FQN).
- Edge drill-down opens a side panel with the helper body inline.
- Effort: ~4–5 days.

**Obsidian-style graph:**
- `react-force-graph-3d` (Three.js renderer) for WebGL at scale.
- Nodes: fields. Edges: mappings. Color: scope. Size: in-degree.
- Search, lasso, hover preview of resolution trail.
- Performance gate: 50k+ edges at ≥30fps on a typical engineer laptop.
- Effort: ~1 week.

---

## 8. Open issues / known limitations

- **Object-creation expressions** (`return new Agent(fi.getBic(), ...)`) inside
  helper bodies aren't resolved. The resolver gives up and the chain bottoms
  out. Workaround for now: tag as `kind=construction`. Real fix: walk the
  constructor body or record the constructor-arg-to-field mapping. Not on
  the critical path.
- **Multi-source binary expressions** (`a + b` where both resolve to source
  fields) currently produce one edge tagged `kind=concat` with one source.
  The second source is lost. Real fix: emit one edge per source with shared
  `expression`.
- **Ternary with mixed sources** — picks the first branch that resolves.
  Same as above: should emit per-branch edges.
- **Unconfigured helper visibility** — when the resolver hits a static call
  to an unconfigured class, it silently falls back. A future commit could
  surface these as a `helper_candidate` table so users see exactly which
  globs to add to `static_helper_classes`. Sized at ~50 LOC.

---

## 9. Files of note

| File | Role |
|---|---|
| `src/atlas/db.py` | SQLite schema. Single source of truth for the data model. |
| `src/atlas/index.py` | Multi-file AST index. Class→file, methods, imports, field types with inheritance walk. |
| `src/atlas/extract.py` | Per-(repo, pair) extractor. `FileWalker` per file. `EntryPoint` assembly. `persist()` writes the DB. |
| `src/atlas/resolvers.py` | Resolver chain. `ParamBinding` (with `path_prefix`), `Resolution`, `_walk_helper_method`, `_alias_caller_bindings`. |
| `src/atlas/schemas.py` | JSON Schema / XSD / `kind: java-class` enumeration. Honors `x-atlas-business-key`, `x-atlas-ignore`. |
| `src/atlas/config.py` | Pydantic models for `atlas.yml`. `Pair.resolvers`, `MethodSelector`, `ResolverConfig`, `SchemaRef`. |
| `src/atlas/cli.py` | Typer CLI: `init`, `extract`, `render`, `validate-config`, `version`. |
| `tests/test_extract.py` | 5 unit tests: tiny-mapstruct, determinism, qualifier+static, multihop, locals. |
| `examples/atlas.*.yml` | Fixture configs: `atlas.yml` (mapstruct), `atlas.qualifier.yml`, `atlas.locals.yml`, `atlas.multihop.yml`. |
| `examples/fixtures/tiny-*` | Hand-authored Maven fixtures. Generated impl files force-added under `target/generated-sources/`. |

---

## 10. Operational notes

- **DB rebuild discipline.** Schema changes are additive *for the SQL* but
  the `edge` table column order changed in commit `8b3c666`. Always run
  `atlas extract --full` after pulling — `--full` triggers `db.reset()`,
  which drops + re-creates from `SCHEMA_SQL`. Without `--full`,
  `CREATE TABLE IF NOT EXISTS` short-circuits on the existing `edge` and
  inserts will fail on column-count mismatch.
- **Scoping the venv.** Every install must hit the same Python env that the
  CLI binary resolves to. After pulling, run from the atlas-lite root:
  `python3 -m venv .venv && .venv/bin/pip install -e .` and use
  `.venv/bin/atlas` for all extract / render commands.
- **Determinism.** Re-running extract on an unchanged tree must produce the
  same `atlas_sha`. The `test_determinism` test enforces this on the small
  fixture; verify on the real codebase periodically with the recipe in §6.7.
- **No-leakage rule.** Source code, helper bodies, and class FQNs from the
  user's real codebase must never be echoed in commit messages, docs, or
  shared output. Use generic placeholders.
