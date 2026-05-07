# Atlas Lite

Pure-Python rewrite of Atlas. Tree-sitter for Java parsing; SQLite as the single source of truth.

**Status:** extractor + renderer + CLI working on the `tiny-mapstruct` fixture. MCP server / web UI planned per `docs/ATLAS_LITE_SPEC.md`.

## Quick start

```bash
uv sync                                           # or: pip install -e .
uv run atlas validate-config --config examples/atlas.yml
uv run atlas extract --config examples/atlas.yml --full --verbose
uv run atlas render  --config examples/atlas.yml
```

Outputs:
- `~/.atlas/atlas.db` — SQLite snapshot.
- `~/.atlas/site/services/<repo>/<pair>/mappers/*.md` — per-mapper Markdown with provenance frontmatter.
- `~/.atlas/site/services/<repo>/graph.jsonld` — per-service JSON-LD.

## Why tree-sitter

- No JVM symbol-solver hangs on large generated impls (the issue that plagued atlas-java's first iteration).
- Native-fast incremental parsing.
- Pure Python install via `tree-sitter` + `tree-sitter-java` wheels.

## Lessons from atlas-java applied

| Pattern | Atlas Lite behavior |
|---|---|
| Multi-parameter MapStruct (`mc, ipa, txInfo`) | Each parameter binds to its own source schema; edges tagged with the actual parameter's type |
| `qualifiedBy = X.class` and `Util.method(src.x)` wrappers | `_extract_source` recurses into call arguments to recover the inner getter chain |
| Helper recursion (`setX(helper(args))`) | Walks helper body with `x` as path prefix; aliases caller bindings into helper params |
| Helper mutators (`Helper.update(target.getX())`) | Detected outside setters; emits `kind=enrichment` |
| Default-method post-processing (`mapFromReturn(target)`) | Method-parameter target vars accepted, not just `new T()` |
| Java-class domain models (no JSON Schema) | `schema_kind: java-class` walks Java classes recursively, honors `@AtlasField` / `@AtlasIgnore` |
| `x-atlas-business-key` for cross-pair joining | Both JSON Schema and XSD walkers honor it; cross-pair query is a recursive CTE in SQLite |
| `x-atlas-ignore` for intentionally-unmapped fields | Honored; excludes from coverage denominator |
| Helper-call wrapper hangs (JavaParser symbol solver) | Tree-sitter has no symbol solver — never hangs |
| Generated impls with 200+ setters | Tree-sitter handles them in milliseconds |

## CLI

```
atlas validate-config  --config atlas.yml
atlas init             --config atlas.yml
atlas extract          --config atlas.yml [--pair <id>] [--repo <id>] [--full] [--verbose]
atlas render           --config atlas.yml [--out <dir>]
atlas version
```

## Layout

See `docs/ATLAS_LITE_SPEC.md` for the full design.
