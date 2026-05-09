import { ArrowRight, ExternalLink, Search, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useFieldSearch, useImpact } from "@/api/hooks";
import type { ImpactRow } from "@/api/types";
import { ScopeChip } from "@/components/scope/ScopeChip";
import { Badge, kindTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { TBody, TableRoot, Td, Th, THead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { fmtCount, shortClass } from "@/lib/format";

export function ImpactRoute() {
  const [params, setParams] = useSearchParams();
  const schema = params.get("schema") ?? "";
  const path = params.get("path") ?? "";

  const [schemaInput, setSchemaInput] = useState(schema);
  const [pathInput, setPathInput] = useState(path);

  // Suggest paths as the user types — reuses /fields with a substring match.
  const suggestion = useFieldSearch(
    pathInput.length >= 2
      ? { schema: schemaInput || undefined, path_prefix: pathInput, limit: 8 }
      : null,
  );

  const query = useImpact(schema && path ? { schema, path } : null);

  useEffect(() => {
    setSchemaInput(schema);
    setPathInput(path);
  }, [schema, path]);

  function run() {
    if (!schemaInput || !pathInput) return;
    const next = new URLSearchParams(params);
    next.set("schema", schemaInput);
    next.set("path", pathInput);
    setParams(next, { replace: true });
  }

  const groups = useMemo(() => groupByScope(query.data?.items ?? []), [query.data]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Sparkles className="h-6 w-6 text-accent" />
          Impact analysis
        </h1>
        <p className="mt-1 text-sm text-fg-muted">
          Pick a source schema and path. Atlas walks every edge that reads from that path (or its
          subtree) and shows you exactly which target fields would change, grouped by scope.
        </p>
      </header>

      <Card>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-12">
          <div className="md:col-span-3 flex flex-col gap-1.5">
            <label className="text-[11px] uppercase tracking-wider text-fg-subtle">
              Source schema
            </label>
            <Input
              value={schemaInput}
              onChange={(e) => setSchemaInput(e.target.value)}
              placeholder="Mt103.json"
              className="font-mono text-[12.5px]"
            />
          </div>
          <div className="md:col-span-7 flex flex-col gap-1.5">
            <label className="text-[11px] uppercase tracking-wider text-fg-subtle">
              Field path (exact or subtree root)
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
              <Input
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") run();
                }}
                placeholder="txInfo.financialInstId.bic"
                className="pl-8 font-mono text-[12.5px]"
              />
            </div>
            {suggestion.data && suggestion.data.length > 0 && pathInput !== path && (
              <div className="surface mt-1 max-h-48 overflow-auto rounded-md p-1 text-[12px]">
                {suggestion.data.map((s) => (
                  <button
                    key={s.id}
                    className="flex w-full items-center justify-between rounded px-2 py-1 font-mono text-left hover:bg-bg-subtle"
                    onClick={() => {
                      setSchemaInput(s.schema_id);
                      setPathInput(s.path);
                    }}
                  >
                    <span className="truncate">{s.path}</span>
                    <span className="text-fg-subtle">{s.schema_id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="md:col-span-2 flex items-end">
            <Button intent="primary" className="w-full" onClick={run} disabled={!schemaInput || !pathInput}>
              Trace
            </Button>
          </div>
        </CardContent>
      </Card>

      {!schema || !path ? (
        <div className="surface rounded-xl px-8 py-16 text-center text-sm text-fg-muted animate-fade-in">
          <Sparkles className="mx-auto h-8 w-8 text-fg-subtle" />
          <p className="mt-3">Enter a source schema and path, then run a trace.</p>
        </div>
      ) : query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : query.error ? (
        <div className="surface rounded-xl p-8 text-center text-sm text-danger">
          {query.error.message}
        </div>
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <div className="surface rounded-xl px-8 py-16 text-center text-sm text-fg-muted">
          No impact: no edge reads from {schema}:{path}.
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-semibold tracking-tight">
              {fmtCount(query.data?.total ?? 0)} affected edge(s) · {groups.length} scope(s)
            </h2>
            <div className="text-[12px] font-mono text-fg-subtle">
              {schema} : {path}
            </div>
          </div>

          {groups.map((group) => (
            <Card key={group.key}>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <CardTitle>
                    <ScopeChip scope={group.scope} />
                  </CardTitle>
                  <CardDescription>{fmtCount(group.rows.length)} edge(s)</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <TableRoot>
                  <THead>
                    <Tr>
                      <Th>Class</Th>
                      <Th>Method</Th>
                      <Th>Target field</Th>
                      <Th>Kind</Th>
                      <Th className="text-right">Line</Th>
                    </Tr>
                  </THead>
                  <TBody>
                    {group.rows.map((row) => (
                      <Tr key={row.edge_id}>
                        <Td className="font-mono text-[12.5px] text-fg/90 max-w-[260px] truncate">
                          {row.class_fqn ? shortClass(row.class_fqn) : "(unknown)"}
                        </Td>
                        <Td className="font-mono text-[12.5px]">{row.method_name ?? "—"}</Td>
                        <Td className="font-mono text-[12.5px] text-fg max-w-[280px] truncate">
                          <span className="text-fg-subtle">{row.target_schema_id}</span>
                          <span className="px-1 text-fg-subtle">·</span>
                          {row.target_path}
                        </Td>
                        <Td>
                          <Badge tone={kindTone(row.kind)} className="normal-case tracking-normal">
                            {row.kind}
                          </Badge>
                        </Td>
                        <Td className="text-right tabular-nums text-fg-muted">
                          {row.browse_url ? (
                            <a
                              href={row.browse_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-accent hover:underline"
                            >
                              L{row.line}
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          ) : (
                            <span>L{row.line}</span>
                          )}
                        </Td>
                      </Tr>
                    ))}
                  </TBody>
                </TableRoot>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

interface ScopeGroup {
  key: string;
  scope: ImpactRow["scope"];
  rows: ImpactRow[];
}

function groupByScope(rows: ImpactRow[]): ScopeGroup[] {
  const map = new Map<string, ScopeGroup>();
  for (const r of rows) {
    const key = `${r.scope.country ?? "*"}|${r.scope.clearing ?? "*"}|${r.scope.product ?? "*"}`;
    let group = map.get(key);
    if (!group) {
      group = { key, scope: r.scope, rows: [] };
      map.set(key, group);
    }
    group.rows.push(r);
  }
  return Array.from(map.values()).sort((a, b) => b.rows.length - a.rows.length);
}

// `cn` is unused on this page intentionally; keep the import path stable
// in case future variants are added without flagging react-refresh.
void cn;
