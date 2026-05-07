# Configuring atlas-lite for a real multi-clearing MapStruct codebase

When the project structure mixes path-based and filename-prefix-based
country/clearing identifiers (e.g. `ar/coelsa/ArCoelsaTranDetailMapperImpl`,
`aus/AuNppTranDetailMapperImpl`, `cn/epcc/EpccTranDetailMapperImpl`).

## Recommended `atlas.yml`

```yaml
version: 1

bitbucket:
  base_url: https://bitbucket.example.net
  api_kind: server
  auth: { token_env: BITBUCKET_TOKEN }
  browse_template: "{base}/projects/{project}/repos/{repo}/browse/{file}?at={sha}#{line}"

repos:
  - id: gxp-payment-service
    path: /absolute/path/to/gxp-payment-service
    project: GXP
    branch: develop

pairs:
  - id: payinit_to_trandetail
    sources:
      - name: MessageContext
        file: schemas/_message_context.json
        kind: json-schema
        type_fqns: ["{PKG}.MessageContext"]
      - name: PaymentInit
        file: schemas/_payment_init.json
        kind: json-schema
        type_fqns:
          - "{PKG}.PaymentInit"
          - "{PKG}.PaymentInit$PaymentInitiation"
    targets:
      - name: TransactionDetail
        file: schemas/_tran_detail.json
        kind: json-schema
        type_fqns: ["{PKG}.TransactionDetail"]

    # MapStruct-only codebase — generated impls hold the truth.
    # The auto-extender adds the corresponding generated-sources path,
    # so you can list ONLY src/main/java here OR ONLY generated-sources.
    # Listing only src/main/java + auto-extension is cleaner.
    scan_globs:
      - "gxp-payment-service/gxp-payment-mapstruct/src/main/java/**/mapper/**/*.java"

    # Scope inference, evaluated in order — first match wins.
    scope_rules:
      # 1. Common scope marker.
      - { glob: "**/mapper/common/**", scope: { common: true } }

      # 2. Path-based: <country>/<clearing>/<...> (two folder levels).
      - glob: "**/mapper/{country}/{clearing}/**"
        capture: [country, clearing]

      # 3. Path-based: <country>/<...> (one folder level).
      - glob: "**/mapper/{country}/**"
        capture: [country]

      # 4. Filename-based fallback for cases where path is flat or country
      #    is encoded only in the class name. The regex matches against the
      #    simple file name (basename); named groups populate scope.
      #
      #    Example: "ArCoelsaTranDetailMapperImpl.java"
      #             -> country=AR, clearing=COELSA
      #
      #    Adjust the country/clearing regex to your domain. The example below
      #    captures camel-prefix country (1-3 chars) + camel-prefix clearing.
      - filename_pattern: "^(?P<country>[A-Z][a-z]{1,2})(?P<clearing>[A-Z][a-zA-Z]{1,15}?)(?:Tran|Txn|Client|Cancel|Return)\\w*MapperImpl?\\.java$"
```

## Scope rule order matters

The first rule that matches wins. Put the most specific (path-based two-level)
first; the filename pattern last as a fallback.

## When path AND filename both encode the same fact

If `cn/beps/CnBepsTranDetailMapperImpl.java` matches the path-based rule first,
the path's `cn`/`beps` win. The filename rule is only consulted when the
path-based rules don't match — typical for flat directories.

## What scope tags become

`_normalise(s)` uppercases and replaces non-alphanumerics with `_`:
- `sg_fast` → `SG_FAST`
- `Coelsa` → `COELSA`
- `cn` → `CN`

These end up in the `mapper.scope_country`, `mapper.scope_clearing`,
`mapper.scope_product`, `mapper.scope_field_group` columns of the SQLite db
(plus `scope_common` boolean), and feed every downstream filter and the
upcoming UI.

## Verify

After running extract, query the DB:

```bash
sqlite3 ~/.atlas/atlas.db <<'SQL'
SELECT scope_country, scope_clearing, COUNT(*) AS mappers
FROM mapper
GROUP BY scope_country, scope_clearing
ORDER BY scope_country, scope_clearing;
SQL
```

You should see one row per (country, clearing) pair with the mapper count.
If a clearing shows up as NULL, your filename_pattern probably needs a tweak —
share the unmatched filename and we'll widen the regex.

## What 100% means here

- **Field level:** every `target.setX(...)` in every Impl produces an edge.
- **Country/clearing level:** every Impl is tagged with its scope (path OR
  filename, whichever rule matches).
- **Product / field_group:** add additional `scope_rules` if your project
  encodes those, using the same pattern.

If a mapper has no scope inferred, that's a config gap, not a code gap. The
`coverage` table records files scanned vs edges emitted; phantom-mapper
suppression (no edges → not a mapper) keeps the count honest.
