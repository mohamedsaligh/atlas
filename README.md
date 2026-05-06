# Atlas

Deterministic field-level lineage extraction for multi-service Maven codebases. **Phase 1**: Java extractor + Python aggregator → Markdown + JSON-LD + SQLite. No LLM in the index — code is the source of truth, `atlas-kb` is a regenerable projection.

---

## Prerequisites

| Tool | Min version | Why |
|---|---|---|
| JDK 17 | 17 | Atlas core + Maven plugin |
| Maven | 3.9 | Build + plugin runtime |
| Python | 3.12 | Aggregator |
| git | 2.30 | SHA capture in manifests |

`uv` is **not** required. Use `pip` + `venv` (works offline once wheels are vendored).

---

## Bootstrapping on a restricted network

The org's machine likely has no internet. Build dependencies on a connected machine, ship them, restore on the target.

### A. On a machine **with** internet

```bash
# 1. Clone Atlas + the user code repos
git clone <atlas-repo> atlas
cd atlas

# 2. Pre-fetch all Maven dependencies into a portable repo
mkdir -p offline/.m2-repo
mvn -Dmaven.repo.local=$(pwd)/offline/.m2-repo dependency:go-offline -DskipTests
mvn -Dmaven.repo.local=$(pwd)/offline/.m2-repo install -DskipTests

# 3. Pre-fetch all Python wheels into a portable wheelhouse
python3.12 -m venv .build-venv
.build-venv/bin/pip install --upgrade pip
.build-venv/bin/pip wheel \
  -w offline/wheelhouse \
  -e packages/atlas-aggregator \
  pytest

# 4. Tar the lot
tar czf atlas-offline-bundle.tgz atlas/
```

`atlas-offline-bundle.tgz` contains:
- the Atlas source tree
- `offline/.m2-repo/` — every Maven jar Atlas needs
- `offline/wheelhouse/` — every Python wheel Atlas needs

### B. On the **restricted** machine

```bash
tar xzf atlas-offline-bundle.tgz
cd atlas

# Java side: tell Maven to use the bundled repo
export ATLAS_M2=$(pwd)/offline/.m2-repo
mvn -Dmaven.repo.local=$ATLAS_M2 -o install -DskipTests   # -o = offline mode

# Python side: install from wheelhouse, not PyPI
python3.12 -m venv .venv
.venv/bin/pip install --no-index --find-links offline/wheelhouse \
  -e packages/atlas-aggregator
```

Add to your shell profile so Maven always uses the bundled repo:

```bash
echo 'export MAVEN_OPTS="-Dmaven.repo.local=$HOME/atlas/offline/.m2-repo"' >> ~/.bashrc
```

### Updating bundles

When Atlas itself changes, repeat step A. The Maven repo grows incrementally (~few MB per release once steady-state); the wheelhouse stays under 30 MB.

---

## Configure `atlas.yml`

Edit `atlas.yml` to point at your real repos and domain pairs:

```yaml
projects:
  - id: my-platform
    repos:
      - id: payment-service
        path: /abs/or/relative/path/to/payment-service       # NO bitbucket needed offline
    domain_pairs:
      - id: mt103_to_local
        source: { name: SWIFT MT103,  schema_file: schemas/swift/MT103.xsd, schema_kind: xsd }
        target: { name: LocalDomain,  schema_file: schemas/local/LocalDomain.json, schema_kind: json-schema }
        scan_packages:
          - "payment-transform/src/main/java/com/x/payment/mapper/common/**"
          - "payment-transform/src/main/java/com/x/payment/mapper/sg/**"
        extractors:
          - type: mapstruct
          - type: plain-java
```

`scan_packages` are globs **relative to the repo root**. The plugin auto-extends with each module's `target/generated-sources/annotations/**`.

Add `x-atlas-business-key: <Concept>` annotations on schema fields (XSD `<xs:appinfo>`, JSON Schema custom keyword) so cross-pair lineage works.

---

## Run

```bash
# 1. Build Atlas (one time + when Atlas changes)
mvn -o install -DskipTests

# 2. Make sure the user's project has fresh generated-sources
cd /path/to/payment-service
mvn -o compile

# 3. Extract
mvn -o com.x.atlas:atlas-maven-plugin:0.1.0-SNAPSHOT:extract \
    -Datlas.config=/path/to/atlas/atlas.yml \
    -Datlas.pair=mt103_to_local

# Output: <repo>/target/atlas/manifests/<pair>.manifest.json + coverage manifest

# 4. Aggregate everything into atlas-kb
cd /path/to/atlas
.venv/bin/atlas-agg build --config atlas.yml --out ./atlas-kb
```

After step 4 you have:

```
atlas-kb/
├── services/<repo>/<pair>/mappers/*.md     # human view, one file per mapper
├── services/<repo>/graph.jsonld            # machine view, per service
├── atlas-global.jsonld                     # machine view, all services
└── index.db                                # SQLite + FTS5 for queries
```

---

## Query

The SQLite index is the fast path until the MCP/UI lands (Phase 2/3).

```bash
sqlite3 atlas-kb/index.db
```

```sql
-- All edges touching DebtorIBAN
SELECT mapper_kind, target_path, source_path, file, line
FROM edges WHERE target_bk = 'DebtorIBAN' OR source_bk = 'DebtorIBAN';

-- Free-text search
SELECT edge_id, target_path, source_path
FROM edges_fts WHERE edges_fts MATCH 'iban';

-- Coverage gap: target fields with no edges
SELECT f.schema_file, f.path
FROM fields f LEFT JOIN edges e ON e.target_path = f.path
WHERE e.edge_id IS NULL AND f.schema_file LIKE '%LocalDomain%';

-- Mapper inventory
SELECT mapper_kind, repo_id, count(*) FROM mappers GROUP BY 1, 2;
```

---

## Verify the install (golden fixture, no external network needed)

```bash
# Reset, compile, extract, aggregate
rm -rf examples/fixtures/payments/source/payment-service/target
mvn -o -f examples/fixtures/payments/source/payment-service/pom.xml compile
mvn -o -f examples/fixtures/payments/source/payment-service/pom.xml \
    com.x.atlas:atlas-maven-plugin:0.1.0-SNAPSHOT:extract \
    -Datlas.config=$(pwd)/atlas.yml -Datlas.pair=mt103_to_local
.venv/bin/atlas-agg build --config atlas.yml --out /tmp/atlas-kb-test

# Run tests
mvn -o test
.venv/bin/python -m pytest packages/atlas-aggregator/tests
```

Expected: 12 Java tests pass, 7 Python tests pass, fixture produces 13 edges across 2 mappers, deterministic on rerun.

---

## Common issues on restricted networks

| Symptom | Likely cause | Fix |
|---|---|---|
| `Could not find artifact ...` during `mvn install` | Maven trying to reach internet | Add `-o` (offline) and ensure `-Dmaven.repo.local=` points at the bundled repo |
| `pip install` says `Could not find a version` | Venv falling back to PyPI | Use `--no-index --find-links offline/wheelhouse` |
| `atlas:extract` silent, `edges=0` | `scan_packages` glob doesn't match | Check the path is relative to repo root, no leading `/` |
| MapStruct `*Impl.java` missing | `mvn compile` not run before `atlas:extract` | Run compile first; the plugin needs the generated sources |
| `manifest checksum mismatch` in aggregator | Java/Python JSON formatting drift (shouldn't happen — both use the same canonical format) | Reinstall both `atlas-core-java` and `atlas-aggregator` from the same source tree |
| Corporate proxy with TLS interception | git/Maven/pip refuse to talk to mirror | Add CA cert to `JAVA_HOME/lib/security/cacerts` and `PIP_CERT`/`REQUESTS_CA_BUNDLE` |

---

## What's in this build

- **`atlas-core-java`** — Edge / Manifest / CoverageManifest models, `@AtlasMapper`/`@AtlasField`/`@AtlasIgnore`/`@AtlasCovers` annotations, `MappingExtractor` SPI, `ScopeInferenceEngine`, deterministic JSON I/O.
- **`atlas-maven-plugin`** — `mvn atlas:extract` Mojo, orchestrator, `mapstruct` and `plain-java` extractors, JavaParser harness with classpath-aware symbol resolution.
- **`atlas-aggregator`** — Python CLI (`atlas-agg build`) that collects + validates manifests, parses business keys from XSD/JSON Schema, builds an in-memory graph, and emits Markdown / JSON-LD / SQLite (FTS5).

Phase 2+ (MCP server, web UI, scheduler, agent) — see `docs/PHASES.md`.

---

## Layout

```
atlas/
├── atlas.yml                    # user config
├── packages/
│   ├── atlas-core-java/         # Java lib
│   ├── atlas-maven-plugin/      # mvn atlas:extract
│   └── atlas-aggregator/        # Python: manifests → atlas-kb
├── schemas/                     # JSON Schemas
├── examples/fixtures/payments/  # golden fixture
├── docs/
│   ├── SPEC.md                  # design baseline
│   └── PHASES.md                # roadmap (phases 2–5)
└── offline/                     # bundled m2-repo + wheelhouse (you create this)
```

---

## Determinism contract

- Same atlas-kb SHA → byte-identical manifests, Markdown, and JSON-LD.
- Edge id = `<service>.<pair>.e_<sha1(file+line+target+source)[:8]>` — stable across reruns.
- Manifest hashed by SHA-256 over its body with the `checksum` field cleared.
- JSON output: sorted keys, 2-space indent, LF newlines, trailing newline. Same in Java (Jackson) and Python (`json.dumps`) — verified by cross-language checksum round-trip.
