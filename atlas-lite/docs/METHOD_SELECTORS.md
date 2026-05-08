# Atlas Lite — Enterprise extraction model

## The pivot

Atlas Lite v0.1 walked every class matching a glob, discovered "mappers"
heuristically (return-type + setter density), and emitted edges per setter.
That works for clean MapStruct-only codebases. It breaks down when:

- A single class has many entry methods producing different transformations
  (e.g. `mapRRCT`, `mapFromPymtInit`, `mapRCDTReturn`, `manualUiCommonMapping`).
- Setters are wrapped by qualifiers (`qualifiers.referenceEndToEndIdentification(...)`)
  whose internal logic Atlas can't see from the impl alone.
- Static helpers (`Util.getDebtorOrgId(...)`) hide the actual source path
  inside their body.

The new model: **the user declares which methods to extract from**, and
Atlas's **resolver chain** follows helper / qualifier / static-method calls
into their source code to recover the true source field path.

## Configuration

`atlas.yml` accepts `method_selectors` alongside the existing `pairs`. When
`method_selectors` is present, it takes precedence; the resulting entry methods
drive extraction.

```yaml
method_selectors:
  - id: trandetail_v1
    description: "All TransactionDetail-producing entry methods across mappers."

    # Pick entry methods. ANY of these match modes work; combine freely.
    selectors:
      # By return type + method name pattern + class pattern.
      - class_pattern:  "^.*\\.mapper\\..*MapperImpl$"
        method_pattern: "^map(From|RRCT|RCDTReturn|Cancel|Return|IcdtAretBeps).*$"
        return_type:    "TransactionDetail"

      # By exact FQN list — most explicit.
      - method_fqns:
          - "com.x.mapper.ar.coelsa.ArCoelsaTranDetailMapperImpl.mapRRCT"
          - "com.x.mapper.cn.beps.CnBepsTranDetailMapperImpl.mapIcdtAretBeps"

    target_schema:
      file: schemas/transaction_detail.json
      kind: json-schema
      type_fqns: ["com.x.domain.TransactionDetail"]

    source_schemas:
      - file: schemas/message_context.json
        kind: json-schema
        type_fqns: ["com.x.context.MessageContext"]
      - file: schemas/payment_init.json
        kind: json-schema
        type_fqns:
          - "com.x.dataobjects.PaymentInit"
          - "com.x.dataobjects.PaymentInit$PaymentInitiation"

    # Resolver chain: when an edge's source path can't be extracted from a
    # direct getter chain, Atlas walks these helper categories.
    resolvers:
      qualifier_classes:
        - "com.x.qualifier.QualifierDefinitions"
        - "com.x.qualifier.*Qualifiers"          # glob
        - "com.x.qualifier.ar.ArQualifiers"      # specific
      static_helper_classes:
        - "com.x.util.MapperQualifierDefinitionsUtil"
        - "com.x.util.*Helper"
      max_depth: 5            # bounded recursion
      follow_intra_class: true

    scope_rules:
      - { glob: "**/mapper/common/**", scope: { common: true } }
      - { glob: "**/mapper/{country}/{clearing}/**", capture: [country, clearing] }
      - { glob: "**/mapper/{country}/**", capture: [country] }
      - filename_pattern: "^(?P<country>[A-Z][a-z]{1,2})(?P<clearing>[A-Z][a-zA-Z]{1,15}?)(?:Tran|Txn|Client|Cancel|Return)\\w*MapperImpl?\\.java$"
```

## Resolver chain

For every `target.setX(rhs)`:

1. **Direct getter chain.** If `rhs` reduces to `<param>.getY().getZ()` on a
   known parameter, source path = `y.z`. Done.
2. **Wrapper-arg recursion.** If `rhs` is a non-getter method call (qualifier
   instance method or static util), descend into the call's arguments looking
   for a getter chain. If found, source path captured + `kind=qualifier` or
   `kind=static_call`.
3. **Qualifier body recursion.** If `rhs` is a method call on an instance of
   a configured qualifier class:
   - Look up the qualifier class file in the multi-file index.
   - Find the named method.
   - Walk its body. If the body returns `someArg.getX().getY()`, attribute
     `x.y` back to the calling argument.
   - Record a `Resolution { kind=qualifier, file, line, helper_fqn }` entry
     in the edge's trail.
4. **Static helper recursion.** Same as qualifier, but for static methods on
   classes listed under `static_helper_classes`.
5. **Intra-class helper recursion.** If `rhs` is `helperName(args)` and
   `helperName` is a sibling method, walk its body with `target_path` as
   prefix (existing behavior).
6. **Conditional / ternary.** Recurse into both branches; emit one edge per
   branch with the branch predicate captured.
7. **Unmatched.** Fall through; emit `kind=expression` with verbatim text and
   no source path. Logged for review.

`max_depth` bounds the recursion (default 5). A cycle detector prevents
infinite loops when helpers call each other.

## Resolution trail

Every edge carries a list of resolution steps. The first step is the
direct setter call; subsequent steps are the helper hops.

```python
@dataclass
class Resolution:
    kind: str          # direct | wrapper_arg | qualifier | static_call | intra_class
    file: str
    line: int
    snippet: str       # the call expression or return statement
    helper_fqn: str | None
```

Persisted in a new SQLite table:

```sql
CREATE TABLE edge_resolution (
    edge_id  TEXT NOT NULL,
    seq      INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    file     TEXT NOT NULL,
    line     INTEGER NOT NULL,
    snippet  TEXT NOT NULL,
    helper_fqn TEXT,
    PRIMARY KEY (edge_id, seq)
);
```

Markdown renderer emits the trail under each edge row. The UI (Phase 2)
shows it as a click-through chain: "edge → qualifier method → return
statement → source field".

## Multi-file index

Built once per extraction run. Walk every `.java` file in `repos[].path`,
parse with tree-sitter, cache:

```python
@dataclass
class JavaIndex:
    cu_by_file: dict[str, tree_sitter.Tree]    # path → parsed tree (cached bytes too)
    class_to_file: dict[str, str]              # FQN → file path
    methods_by_class: dict[str, dict[str, Node]]  # FQN.method → AST node
    imports_by_file: dict[str, dict[str, str]]    # file → simpleName → FQN
    field_types: dict[str, dict[str, str]]        # class FQN → field name → declared type
```

Used by every resolver step. Built in parallel (one worker per repo). Memory
cost is modest — tree-sitter ASTs are compact bytes references.

## Backwards compatibility

- `pairs` keep working unchanged. Configs without `method_selectors` get the
  current behavior.
- `method_selectors` and `pairs` can coexist; results are merged by edge_id.
- The `resolvers` block can be added to either `pairs` or `method_selectors`
  with the same semantics.

## What 100% means under this model

- **Field-level**: every setter call inside a selected entry method's
  reachable call graph (bounded by max_depth) emits an edge with the actual
  source field path, even when wrapped by qualifiers or static helpers.
- **Coverage denominator**: target schema enumerated; written-paths
  subtracted; gap is the unmatched set. With qualifier following, far fewer
  edges fall through to `kind=expression` with `source=null`.
- **Audit**: the resolution trail proves how each edge was derived. Every
  step links to source code. No black boxes.

## Operational characteristics

| Concern | Behavior |
|---|---|
| **Determinism** | Same atlas.yml + same repo SHA → byte-identical SQLite. Resolver chain is deterministic; ordered children, sorted maps. |
| **Performance** | Multi-file index built once. Resolutions cached by (caller_class, helper_fqn, args_shape). Tree-sitter parse: ~5ms/file; full scan of 500 files ≤ 3s. |
| **Resilience** | A file that fails to parse goes to `coverage.unparseable_json`. A helper that can't be located emits the original wrapper edge with no further trail. Build doesn't crash on a single broken helper. |
| **Bounded recursion** | `max_depth` and a per-extraction visited set prevent runaway recursion. |
| **Observability** | Verbose mode logs every helper resolution: hit / miss / max-depth-reached. Counters published in coverage table. |
| **Security** | Static analysis only. No `Class.forName`, no reflection, no execution. Tree-sitter parses raw bytes. |
| **Extensibility** | Resolver registry — adding new resolver kinds (e.g. Lombok `@Builder` chain following) is one new function + a config flag. |

## Roadmap (after this commit)

| Slice | What |
|---|---|
| Day 1 (this) | Design doc, config schema, scaffolding, qualifier + static helper following |
| Day 2 | Resolution trail in DB + Markdown render of the trail |
| Day 3 | Parallel parsing + AST cache eviction policy |
| Day 4 | Conditional-branch per-edge emission |
| Day 5 | Method-selector-only extraction mode (no `pairs` required) |
| Day 6 | Adversarial validator suite for resolver-chain correctness |
| Day 7 | UI surface to navigate resolution trails |

The architecture survives all of these; each is additive on the resolver
chain and the index.
