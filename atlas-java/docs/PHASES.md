# Atlas — Phase Roadmap

Phase 1 (extractor + aggregator + atlas-kb) shipped. This document covers every phase remaining: background, scope, modules, contracts, exit criteria, and open decisions. Each phase is self-contained enough for a developer to begin without re-reading the conversation history.

> **Anchoring docs.**
> - `docs/SPEC.md` — original 1425-line baseline (imported from Claude Web).
> - This file (`docs/PHASES.md`) — locked decisions through iteration; the only roadmap that supersedes the baseline.
> - The 12 user-facing constraints from the conversation (config-driven scope, type-pair gate, deterministic outputs, schema-annotation business keys, plugin SPI, no-LLM index) hold across **every** phase below.

---

## Cross-phase invariants (must hold in 2 → 5)

These are non-negotiable for any module added later.

| # | Invariant | Why |
|---|---|---|
| 1 | Code is the source of truth; atlas-kb is a regenerable projection | Drift safety; rebuild from any SHA reproduces the world |
| 2 | Same atlas-kb SHA → byte-identical query responses | Cache, audit, share |
| 3 | Every API/UI value carries `(repo, sha, file, line, browseUrl)` provenance | Anti-hallucination + click-through |
| 4 | Plugin extractor SPI surface stays additive | New `EdgeKind`, new `mapper_kind` only appended |
| 5 | LLMs never write to the index, only read | One-way trust gradient: code → extractor → KB → MCP → agent |
| 6 | Validator gates every agent-authored output | Atom-grep against tool transcript before user/CI sees text |

---

## Phase 1.5 — Encoder extractors (carry-over slice)

Small, contained backlog item carved out of Phase 1.

### Background

Phase 1 fixture only exercised MapStruct + plain-Java mappers. The user's actual codebase has sanctions / clearing outbound services that emit fixed-length and tag/length/value formats. The SPI was designed for them; the work left is two extractors plus one fixture.

### Modules

| Path | Description |
|---|---|
| `packages/atlas-maven-plugin/src/main/java/com/x/atlas/plugin/extractors/encoders/FixedLenEncoderExtractor.java` | Walks `StringBuilder`/`Formatter`/`padRight`/`padLeft` calls; emits edges with `formatSpec: {offset, length}` |
| `packages/atlas-maven-plugin/src/main/java/com/x/atlas/plugin/extractors/encoders/TaggedEncoderExtractor.java` | Walks `out.write("32A", value)`-style calls; emits edges with `formatSpec: {tag}` |
| `examples/fixtures/payments/source/payment-service/payment-transform/src/main/java/com/x/payment/encoder/common/SanctionsFixedLenEncoder.java` | One synthetic encoder mapper |
| `examples/fixtures/payments/source/payment-service/payment-transform/src/main/resources/sanctions-spec.yaml` | Target schema (fixed-length spec) |

### Edge model addition

`EdgeKind` already supports `format`. The `formatSpec` field on `Edge` is open-ended JSON; encoders populate `{offset, length}` or `{tag}` accordingly. No core schema change required.

### Exit criteria

- `mvn atlas:extract` over the new fixture produces ≥ 5 fixed-length edges and ≥ 3 tagged edges.
- Each edge has a populated `formatSpec`.
- Aggregator round-trips the new edges through Markdown + JSON-LD + SQLite without changes.
- Determinism check: byte-identical output across reruns.

### Open decisions

1. Is the user's fixed-length encoder DSL a generic `StringBuilder.append(...)` pattern, or a project-specific helper (`Field.write(out, "32A", value)`) that needs a custom matcher? — Answer determines whether one generic extractor handles all 50+ clearings or each clearing needs a sub-matcher behind the same SPI id.
2. Tag/length/value: confirm the actual Java API used in the user's tagged encoders.

### Estimated effort

3–5 days, single developer.

---

## Phase 2 — Query layer (MCP server, Bitbucket-MCP, validator, REST shim)

### Background

Phase 1 produces atlas-kb at rest (Markdown + JSON-LD + SQLite). Without a query layer, only humans browsing files can use it. Phase 2 makes atlas-kb addressable to:
- **Agents** (Claude / any MCP-speaking model) via stdio/HTTP MCP.
- **The UI** (Phase 3) via REST mirror.
- **Bitbucket** via a typed read-only proxy that guarantees SHA-pinned reads (the second half of the no-hallucination contract).

This is the load-bearing phase; UI and agent are blocked on it.

### Modules

| Path | Language | Purpose |
|---|---|---|
| `packages/atlas-mcp-server/` | Python 3.12 | FastAPI app exposing MCP tools + REST mirror |
| `packages/atlas-bitbucket-mcp/` | Python 3.12 | SHA-pinned Bitbucket reads via `httpx` |
| `packages/atlas-validator/` | Python 3.12 | Atom-grep validator (pre-flight + post-flight) |

All three share `packages/atlas-aggregator/` (Phase 1) for Pydantic models — no duplication.

### MCP tool surface

Standard envelope on every tool response (Pydantic `Envelope[T]`):

```python
class Meta(BaseModel):
    count: int
    complete: bool
    next_cursor: str | None
    atlas_sha: str
    query_hash: str
    invariants_checked: list[str]   # ["sealed", "checksum_ok", "count_in_band"]

class Envelope(BaseModel, Generic[T]):
    data: list[T]
    meta: Meta
    provenance: list[ProvenanceRecord]
```

Tools (all SQLite-backed, deterministic):

| Tool | Inputs | Returns |
|---|---|---|
| `pin_atlas_sha(sha)` | sha | confirmation; subsequent calls in same session use this snapshot |
| `find_field(query, limit, cursor)` | text query (FTS5) | matching fields with sources/targets |
| `find_mapper(query, mapper_kind?)` | text + optional kind filter | matching mappers |
| `get_edge(edge_id)` | edge_id | single edge with full provenance |
| `trace_lineage(field_id, direction)` | source/target field, upstream/downstream | edges traversed across pairs |
| `mappers_by_scope(common?, country?, clearing?, product?, fieldGroup?)` | scope filters | mappers in scope |
| `compare_models(left_schema, right_schema, scope)` | two schema files + filters | field-by-field rows: green/amber/red/gray |
| `impact_of_change(change_spec)` | rename/drop/add/format spec | blast radius: edges, services, missing tests |
| `tests_for_edges(edge_ids)` | edge ids | edge → covering tests + gaps |
| `verify_edges(edge_ids)` | edge ids | round-trip confirmation |
| `coverage_health()` | none | per-service `% tests`, `% with business_key`, drift |

### Bitbucket-MCP tool surface

| Tool | Inputs | Returns |
|---|---|---|
| `bb.read_file(repo, sha, path, line_from?, line_to?)` | repo coords + SHA-pinned path | exact bytes; fails on blob_sha drift vs Atlas record |
| `bb.diff(repo, sha_a, sha_b, path?)` | two SHAs + optional path | typed diff hunks |
| `bb.pr_for_sha(repo, sha)` | repo + SHA | PR id, title, author, reviewers, decision |
| `bb.search_code(query, repo?, branch?)` | text query | matches; only used when Atlas can't answer |

### Validator contract

```python
ATOM_PATTERNS = {
    "edge_id":    r"\b[a-z0-9-]+\.[a-z0-9_-]+\.e_[0-9a-f]{8}\b",
    "mapper_fqn": r"\b(?:[a-z][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_]+(?:#[a-zA-Z0-9_]+)?\b",
    "file_path":  r"\b(?:[\w-]+/)+[\w.-]+\.(?:java|json|xsd|yaml|md)\b",
    "url":        r"\bhttps?://\S+\b",
    "sha":        r"\b[0-9a-f]{7,40}\b",
}

def validate(draft: str, transcript: list[ToolCall]) -> ValidationResult:
    """Every atom in `draft` must appear verbatim in some response of `transcript`.
    Returns list of unverifiable atoms (kind, value, offset)."""
```

Two enforcement points:
1. **Pre-flight** — agent calls `validate_response(draft)` before showing user. Drafts with unverifiable atoms get rewritten or refused.
2. **Post-flight** — CI hook on agent-authored PRs runs the same validator over PR bodies and code comments.

### Determinism guarantees

- SQLite opened in **read-only sealed mode** (`mode=ro&immutable=1`).
- New atlas-kb SHA → MCP builds shadow index in temp dir → row-count invariant check → atomic `os.rename`.
- `pin_atlas_sha` causes subsequent tool calls in that session to resolve against that SHA only — the world cannot shift mid-plan.
- Same `(atlas_sha, tool, args)` returns byte-identical bytes; tested via property test in `tests/`.

### REST shim

The web UI (Phase 3) speaks HTTP/JSON. Same FastAPI app exposes both:

```
POST /mcp                 # MCP protocol over JSON-RPC (for stdio MCP via mcp-proxy or HTTP)
GET  /api/v1/find_field   # REST mirror auto-generated from MCP registry
GET  /api/v1/trace_lineage
...
```

`register_rest(mcp_app)` walks the MCP tool registry and adds REST routes — one source of truth, no duplication.

### Module file layout

```
packages/atlas-mcp-server/
├── pyproject.toml
├── src/atlas_mcp_server/
│   ├── server.py                # FastMCP app + FastAPI REST shim
│   ├── db.py                    # snapshot lifecycle + atomic swap
│   ├── envelopes.py             # Pydantic envelope + Meta types
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── find_field.py
│   │   ├── trace_lineage.py
│   │   ├── compare_models.py
│   │   ├── impact_of_change.py
│   │   └── ...
│   ├── invariants.py            # row-count band, checksum verify on snapshot load
│   └── rest.py                  # REST mirror generation
└── tests/
    ├── test_determinism.py      # property: same args → same bytes
    ├── test_pinning.py          # pin holds across calls
    └── test_envelope_complete.py # complete=False forces pagination

packages/atlas-bitbucket-mcp/
├── pyproject.toml
├── src/atlas_bitbucket_mcp/
│   ├── server.py
│   ├── client.py                # httpx async client + token auth
│   └── drift.py                 # blob_sha verification vs Atlas
└── tests/

packages/atlas-validator/
├── pyproject.toml
├── src/atlas_validator/
│   ├── validate.py
│   ├── patterns.py              # ATOM_PATTERNS
│   └── transcript.py            # extract atoms from MCP tool transcripts
└── tests/
    └── adversarial/             # paired drafts + transcripts; library of bad examples
```

### Exit criteria

- All MCP tools answer over the Phase 1 fixture; round-trip `(args) → bytes → bytes`.
- REST endpoints return the same data as their MCP counterparts byte-for-byte.
- Bitbucket-MCP refuses reads when `blob_sha` doesn't match Atlas-recorded value.
- Validator catches every adversarial-test atom in `tests/adversarial/` (≥ 20 hand-crafted hallucination drafts).
- `pin_atlas_sha` → 5 subsequent tool calls all resolve to that SHA.
- A complete-pagination test: tool with `limit=2` over 7-row fixture returns `complete: false`, `next_cursor`, and the cursor walks.

### Open decisions

1. **Auth model.** Read-only MCP & REST: open inside cluster? OIDC for human users on REST? PAT for stdio MCP? Pick before any deployment.
2. **`atlas-kb` storage.** Bitbucket Server, GitHub, or local clone path? `atlas.yml.storage.atlas_kb_repo` already supports both; need to confirm canonical for the team.
3. **Session model for MCP.** Stateless tools (every call passes `atlas_sha`) vs. session-scoped (`pin_atlas_sha` once)? Spec assumes session-scoped via the MCP server's request lifecycle — confirm with whoever wires Claude Code.
4. **Bitbucket token rotation.** Service account vs OAuth app — needed for the scheduler too (Phase 4); decide once for both.
5. **Rate limiting.** MCP and REST behind the same FastAPI; pick a token-bucket approach (slowapi, or write our own).

### Estimated effort

3–4 weeks, one developer. MCP server is the bulk; validator and Bitbucket-MCP each ~3 days.

---

## Phase 3 — Web UI

### Background

Atlas's WOW factor lives here. Senior management's demo is the Sankey diagram and the impact-analysis dashboard. Developers' daily-driver is the field search. Both depend on Phase 2's REST shim.

### Stack (locked through prior conversation)

| Concern | Pick |
|---|---|
| Framework | React 19 |
| Build | Vite 6 |
| Routing | TanStack Router |
| Data | TanStack Query |
| Tables | TanStack Table |
| Styling | Tailwind v4 + custom editorial-dark theme |
| Lineage diagram | D3-sankey |
| Markdown rendering | unified + remark + rehype |
| State | TanStack Query + URL state (SHA in `?atlas_sha=…`) |
| Type generation | `pydantic2ts` from Phase 2 Pydantic models — auto-generates `types.ts` |

### Theme — editorial-dark

Per spec §12.1, this is opinionated and locked:

- **Surfaces.** Near-black (`#0a0a0a`) base, layered to `#161616`, `#1f1f1f`. No pure black, no gradients.
- **Type.** Söhne (or Geist Sans as free fallback) for prose; JetBrains Mono for IDs, paths, code; Söhne Mono for tabular numerals.
- **Accent.** One — warm amber (`#f59e0b`) for active state and Sankey flows. No teal, no purple, no SaaS rainbow.
- **Borders.** 1px hairlines (`#262626`). No shadows, no glassmorphism.
- **Density.** Editorial — long paragraphs allowed in mapper docs; impact dashboards stay terse.

The UI must feel like a financial-grade research tool, not a SaaS landing page.

### Surfaces

| Route | Page | Primary tool calls |
|---|---|---|
| `/` | Health dashboard (default landing) | `coverage_health` |
| `/search?q=…` | Field search | `find_field` |
| `/field/:schema/:path` | Field detail (sources, targets, mappers, business key) | `find_field`, `trace_lineage` |
| `/lineage?source=…&target=…` | D3-sankey lineage view, scope filters | `trace_lineage` |
| `/compare?left=…&right=…` | Schema-to-schema diff | `compare_models` |
| `/impact` | Change spec form → blast-radius dashboard | `impact_of_change`, `tests_for_edges` |
| `/mapper/:id` | Markdown view + edge table | direct GET on atlas-kb file |
| `/edge/:id` | One edge with code link, history | `get_edge`, `bb.read_file` |

### Components (atomic, per surface composition)

```
src/components/
├── ProvenanceBar.tsx       # hover any cell → {repo, sha, file, line, browseUrl}
├── EdgeTable.tsx           # TanStack Table; columns = edge_id, source, target, kind, expr, confidence
├── LineageSankey.tsx       # D3-sankey wrapper; width-by-edge-count; click → mapper page
├── FieldSearchBar.tsx      # autocomplete via FTS, debounce 200ms, atlas_sha pinned
├── ImpactForm.tsx          # change_type ∈ rename|drop|add|format; submits to MCP
├── BlastRadiusPanel.tsx    # services × edges × clearings table; gap list; rollout topology
├── CoverageHeatmap.tsx     # service × country, % tests, color-graded
├── DriftChart.tsx          # mapper count over time
├── MarkdownViewer.tsx      # rehype-react with provenance hover on every code block
└── ShaPinIndicator.tsx     # always-visible top-right; click → "view at HEAD" or "copy share link"
```

### Anti-hallucination guarantees in the UI

Same three locks as Phase 2's MCP:

1. **One source.** UI reads only from `/api/v1/*`. No inline data, no derived static JSON.
2. **Provenance on every cell.** Tooltip with `{repo, sha, file, line}`. Click any value → opens that line in Bitbucket at that SHA.
3. **SHA in URL.** Every page URL contains `?atlas_sha=…`. Share with a colleague: they see the same world.

### Module file layout

```
packages/atlas-web/
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── tsconfig.json
├── public/
│   └── fonts/
└── src/
    ├── main.tsx
    ├── routes/
    │   ├── _layout.tsx
    │   ├── index.tsx           # health
    │   ├── search.tsx
    │   ├── field/$schema/$path.tsx
    │   ├── lineage.tsx
    │   ├── compare.tsx
    │   ├── impact.tsx
    │   ├── mapper/$id.tsx
    │   └── edge/$id.tsx
    ├── components/             # atoms, see above
    ├── api/
    │   ├── client.ts           # fetch wrapper with atlas_sha pinning
    │   ├── tools.ts            # generated from MCP tool schemas
    │   └── types.ts            # generated by pydantic2ts
    ├── theme/
    │   ├── tokens.ts           # design tokens (color, type, space)
    │   └── globals.css
    └── lib/
        ├── sankey.ts           # D3-sankey layout helpers
        └── url.ts              # SHA-pin serialization in URL
```

### Skills/tools to use during build

The user asked for these by name in the original request:

- **`frontend-design`** skill — distinctive, production-grade interfaces; avoids generic AI aesthetics.
- **`ui-ux-pro-max`** skill — color systems, font pairings, layout, accessibility, animation.
- **`theme-factory`** (if available) — editorial-dark theme tokens.
- **`shadcn/ui` MCP** — component primitives that match the editorial style after restyling.

### Exit criteria

- All seven routes render against fixture data (Phase 1 SQLite, served by Phase 2 REST).
- Sankey diagram for `MT103.field_50K → LocalDomain.dbtrAcct.iban` renders, click-through opens correct line in Bitbucket.
- Impact form: submitting a rename for the fixture lists every affected edge with `tests_for_edges` gaps.
- Theme passes accessibility (AA contrast, keyboard navigation, focus visible).
- SHA-pin URL: copy/paste between two browsers shows identical state.
- Lighthouse performance score ≥ 90 on `/search` and `/lineage`.

### Open decisions

1. **Authentication.** Read-only browsing inside corporate VPN? OIDC + groups for mutating actions (impact → JIRA)?
2. **Embed mode.** Render specific routes inside an iframe for Confluence / JIRA gadgets?
3. **Custom domain / hosting.** Vercel, Netlify, or behind the same FastAPI server (single binary)?
4. **Server-side render?** Phase-1 answer = no, client-only. Revisit only if SEO matters for an internal portal (it doesn't).

### Estimated effort

4–6 weeks, one front-end developer. Sankey + impact dashboard are the long poles.

---

## Phase 4 — Scheduler & continuous extraction

### Background

Phase 1 extraction is manual (`mvn atlas:extract`). For Atlas to be daily-trustworthy, the index must rebuild on every merge. Phase 4 closes the loop:

```
dev pushes PR → CI extracts → PR comment with impact → merge to main → 
scheduler full-rescan within 6 hours → atlas-kb auto-PR → MCP hot-reloads
```

### Modules

| Path | Description |
|---|---|
| `packages/atlas-scheduler/` | Python 3.12 + APScheduler + GitPython |

### Two operating modes

**Pull (scheduler-driven).**
1. Cron fires per `atlas.yml.auto_learning.default_schedule.{full_rescan,incremental}`.
2. For each repo: shallow clone (or fetch existing) into `~/.atlas/cache/<repo>` at tracked branch.
3. `mvn atlas:extract` for each pair.
4. `atlas-agg build` aggregates into a temp atlas-kb.
5. Diff vs current atlas-kb → if changed, open PR with auto-merge label.
6. POST `/admin/reload` on MCP server → SQLite atomic swap.

**Push (CI-driven).**
1. Bitbucket pipeline on merge to main posts `repository_dispatch` to scheduler's `/webhook`.
2. Same pipeline as Pull, scoped to one repo.
3. Faster path; latency ≈ 2–10 minutes.

### Drift gate (already in Phase 1's coverage manifest, enforced here)

- Mapper count drops > 2σ vs rolling baseline → block atlas-kb merge.
- Override: PR comment `/atlas accept-delta` runs the merge with `accepted: true` recorded in `coverage-manifest.drift`.
- Weekly digest (Slack) lists top-3 services with rising `unmatchedTargetFields` or shrinking test coverage.

### CI integration (PR-time)

A GitHub App / Bitbucket bot (separate package, ~300 LOC) does:
1. On PR open/update: shallow checkout, run `mvn atlas:extract` for affected packages.
2. Diff vs base SHA's manifest → identify changed/added/removed edges.
3. Compute downstream impact via `impact_of_change` MCP call.
4. Post a single PR comment:
   ```
   This PR changes 3 mappers, affects 7 downstream services across 2 clearings (SG_FAST, IN_BI_FAST).
   2 JUnits missing for the new field. Suggested test stubs attached.
   ```
5. JUnit suggestion attached as a code-suggestion review comment.

### Module file layout

```
packages/atlas-scheduler/
├── pyproject.toml
├── src/atlas_scheduler/
│   ├── main.py                  # APScheduler boot
│   ├── config.py                # reads auto_learning section
│   ├── runners/
│   │   ├── full_rescan.py
│   │   ├── incremental.py
│   │   └── per_repo.py          # honors per_repo_overrides
│   ├── git/
│   │   ├── clone.py             # GitPython + sparse checkout
│   │   └── publish.py           # opens PR on atlas-kb
│   ├── webhook.py               # FastAPI /webhook for push mode
│   ├── notifications/
│   │   ├── slack.py
│   │   └── digest.py            # weekly drift report
│   └── reload.py                # POST /admin/reload to MCP server
└── tests/
    ├── test_drift_gate.py
    └── test_pr_open_flow.py
```

### Exit criteria

- Push mode: webhook → atlas-kb auto-PR within 10 minutes for the fixture (artificial repository_dispatch via curl).
- Pull mode: cron tick `*/5 * * * *` → drift detection runs, no-op when nothing changed.
- Drift gate: forced `mappersDetected` drop in manifest → atlas-kb PR blocked, comment includes baseline + sigma.
- Slack digest: weekly cron emits a JSON payload (verifiable with httpbin sink in tests).
- CI bot: open PR on fixture with one mapper edit → bot comments with affected services and test gaps.

### Open decisions

1. **`atlas-kb` ownership.** Who reviews auto-merge PRs? Single SRE? CODEOWNERS list? Forced auto-merge after green CI? Decide *before* turning push mode on or PRs pile up.
2. **CI runner.** GitHub Actions, Bitbucket Pipelines, Jenkins, or all three? Spec defaults to GHA via `repository_dispatch`; on-prem may force Jenkins.
3. **Notification routing.** Slack channel vs Teams vs email? Spec ships Slack only.
4. **Secrets.** Bitbucket token + Slack webhook + JIRA token (Phase 5) all live in env or Vault — pick one, not three different stores.
5. **Cache eviction.** `~/.atlas/cache` will grow; LRU? Per-repo TTL? Default 30 days, deleted-repo cleanup quarterly.

### Estimated effort

2–3 weeks. Most of the work is integration glue + notification wiring, not new logic.

---

## Phase 5 — Agent integration

### Background

Atlas's headline ambition: natural-language → impact analysis → JIRA epic + child tickets + per-service refactor PRs + JUnit stubs. Everything before this phase is plumbing for the moment a developer asks: *"Plan a rename of `localDomain.dbtr.acct.iban` to `debtorAccount.iban`."*

### Module

| Path | Description |
|---|---|
| `packages/atlas-agent/` | Python orchestrator + Claude system prompt + JIRA MCP integration |

### Capabilities (each gated by validator, all read through MCP)

1. **Refactor planning** — given a rename/drop/format change, produce:
   - Per-service refactor PRs (one per repo).
   - JIRA epic with child tickets ordered topologically.
   - JUnit stubs for new edges.
   - Rollout order respecting service dependency topology.
2. **Impact analysis (conversational)** — wraps `impact_of_change` MCP. Output is identical to UI's `/impact` page but as Markdown.
3. **Coverage gap remediation** — for any list of edges, generate JUnit stubs from real schema sample messages.
4. **Onboarding tour** — new joiner asks "How does SG_FAST inward work?" → agent traces lineage and explains with code links.
5. **Schema evolution review** — when source/target schemas add fields, list new `unmapped` edges, suggest mapper updates.

### Anti-hallucination contract (the load-bearing mechanism)

System-prompt rule (literal, encoded in `prompt.md`):

> Every edge_id, mapper FQN, field name, country code, and clearing code in your output must appear verbatim in some MCP response from the same conversation. Before showing your output, call `validate_response(draft)`. If unverifiable atoms exist, rewrite or refuse.

Two enforcement points (already shipped in Phase 2):
- **Pre-flight.** Agent self-validates before user-visible output.
- **Post-flight.** CI runs validator over PR bodies and code comments authored by the agent.

This means **the agent literally cannot fabricate an edge id**. The validator catches it before the user sees the text.

### Workflow — refactor of `localDomain.dbtr.acct.iban`

```
1. user → "rename localDomain.dbtr.acct.iban to debtorAccount.iban"
2. agent → MCP.pin_atlas_sha("abc123")
3. agent → MCP.find_field("localDomain.dbtr.acct.iban")
   ← 1 field, businessKey=DebtorIBAN, complete:true
4. agent → MCP.trace_lineage(field_id, "downstream")
   ← 74 edges, 12 services, 8 clearings, complete:true
5. agent → MCP.tests_for_edges([...74 ids...])
   ← 51 tests, 23 gaps
6. agent → MCP.verify_edges([...74 ids...])
   ← all confirmed at atlas_sha=abc123
7. agent drafts plan; validate_response() greps every FQN, edge_id, file path
8. agent → JIRA.create_epic + 12 child tickets
9. agent → for each repo: bb.read_file (current) → produces refactor diff
   → opens 12 PRs via Bitbucket API, each with JUnit stubs
10. agent → returns summary URL with provenance per row
```

### Module file layout

```
packages/atlas-agent/
├── pyproject.toml
├── src/atlas_agent/
│   ├── orchestrator.py          # the main planning loop
│   ├── prompts/
│   │   ├── refactor.md
│   │   ├── impact.md
│   │   ├── onboarding.md
│   │   └── coverage_remediation.md
│   ├── tools/
│   │   ├── atlas.py             # wraps Phase 2 MCP
│   │   ├── bitbucket.py         # wraps Phase 2 bb-mcp
│   │   ├── jira.py              # JIRA MCP integration
│   │   └── validator.py         # wraps Phase 2 atlas-validator
│   ├── plans/
│   │   ├── refactor_plan.py     # Pydantic model for an executable plan
│   │   ├── junit_stub_gen.py    # template-based stub generator
│   │   └── pr_scaffold.py       # diff + PR open
│   └── safety.py                # blast-radius limits, confirmation prompts
└── tests/
    ├── test_refactor_plan_for_fixture.py
    ├── test_validator_blocks_invented_edge.py
    └── golden/
        └── rename_iban/         # input → expected plan → expected PRs (snapshot)
```

### Safety guards (separate from validator — covers actions, not text)

| Guard | Behavior |
|---|---|
| Blast-radius cap | Refuses plans affecting > 50 mappers without explicit user confirmation |
| Topology preview | Shows rollout order before opening any PR |
| Dry-run default | First call always returns "preview" mode; user re-asks with "execute" to actually open PRs/JIRAs |
| Per-repo PR limit | Max 1 open PR per repo from agent at a time (prevents cascading mistakes) |
| Authorization | PR creation requires user identity attached to the request; CI validator rejects unauthorized agent PRs |

### Exit criteria

- Refactor demo on fixture: agent produces a plan that lists every edge by id, every file path, every line — all validator-passing.
- Coverage demo: agent generates 5 JUnit stubs for the fixture's coverage gaps; stubs compile against fixture mapper.
- Hallucination test: feed the agent a transcript with edge ids; assert the agent NEVER outputs an edge id absent from the transcript (run via property test).
- JIRA round-trip: epic + 3 child tickets created and visible in JIRA staging environment.
- Latency: simple impact query returns < 5s; full refactor plan < 60s for fixture-scale.

### Open decisions

1. **Which model.** Default Opus 4.7 (Phase 1's environment). Cheaper variants (Haiku 4.5) for impact-only flows.
2. **Where the agent runs.** Claude Code (developer-local) is the v0 surface — no extra infra. Slack bot or web chat are v1 surfaces.
3. **JIRA project / workflow.** Confirm `jira.default_project` and the issue-types used (Epic / Story / Task).
4. **Refactor authorization.** Who can run agent-execute mode? Tech-lead-only for the first 90 days, then opened up?
5. **Cost monitoring.** Token spend per refactor — set per-conversation cap and per-month budget alert.

### Estimated effort

3–5 weeks. Not because the code is large (it isn't — it's mostly prompt + tool wiring) but because integration testing across MCP + JIRA + Bitbucket + Claude is iterative.

---

## Phase ordering rationale

Why this order is the correct one:

- **2 first.** UI and agent are useless without typed read access to atlas-kb. Validator is needed before any LLM-authored text reaches a human.
- **3 second.** UI is the demo that sells the project to stakeholders. Without it, Atlas remains an internal CLI no executive will champion.
- **4 third.** Once the index is queryable and the UI is impressive, automate the rebuild loop so freshness is invisible. Until 2+3 exist, nobody cares about freshness.
- **5 last.** Agent has the most leverage but the most prerequisites — needs 2 (data), 3 (UX surface for users to land in), 4 (fresh data the agent can trust on Tuesday morning).

A common trap is to swap 3 and 4 ("just make it auto-update first, UI can wait"). Don't. Without the UI, the project has no demo, no champions, no political fuel for the operational investment of phase 4.

---

## Quick reference — totals

| Phase | Modules added | Java | Python | TS | Estimated weeks |
|---|---|---|---|---|---|
| 1 (done) | atlas-core-java, atlas-maven-plugin, atlas-aggregator | ✓ | ✓ | — | 6–8 |
| 1.5 | encoder extractors + fixture | ✓ | — | — | 1 |
| 2 | atlas-mcp-server, atlas-bitbucket-mcp, atlas-validator | — | ✓ | — | 3–4 |
| 3 | atlas-web | — | — | ✓ | 4–6 |
| 4 | atlas-scheduler + CI bot | — | ✓ | — | 2–3 |
| 5 | atlas-agent | — | ✓ | — | 3–5 |
| **Total remaining** |  |  |  |  | **13–19 weeks** |

One-developer rough estimate. With two developers in parallel (one back-end, one front-end), Phase 2 + 3 collapse into one window — total drops to ~10–13 weeks.
