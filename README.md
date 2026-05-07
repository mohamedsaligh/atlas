# Atlas

Deterministic field-level lineage extraction for multi-service codebases. Two implementations live side by side:

| Path | Stack | Status |
|---|---|---|
| **`atlas-java/`** | Java extractor (Maven plugin) + Python aggregator | Phase 1, working |
| **`atlas-lite/`** | Pure Python (tree-sitter) + React/TS UI | New, in development |

Both implementations share the same architectural commitments:

- Code is the source of truth; the KB is a regenerable projection.
- Same `atlas.yml` SHA → byte-identical outputs.
- Every fact carries `(repo, sha, file, line, browse_url)` provenance.
- Build fails loudly on unparseable input — no silent skips.

## Choosing between them

**`atlas-java/`** — the production-tested one. Uses MapStruct's generated `*Impl.java` parsed with a fast text/regex extractor (no JavaParser, no symbol solver). Ships:
- Maven plugin: `mvn atlas:extract`
- Python aggregator: `atlas-agg build`
- SQLite + FTS5 index, Markdown + JSON-LD output.

**`atlas-lite/`** — the rewrite. Single Python project + React UI. Uses tree-sitter for Java parsing (purpose-built for fast, incremental parsing of any-size files). Ships once stable:
- `atlas extract | render | serve` CLI.
- MCP server + REST shim.
- React UI with Sankey lineage and impact analysis.

Pick `atlas-lite` for new deployments. `atlas-java` remains for environments that already depend on it.

## Quickstart

```bash
# atlas-java
cd atlas-java && mvn install -DskipTests

# atlas-lite
cd atlas-lite && uv sync && uv run atlas extract --config atlas.yml
```

See each subproject's README for details.
