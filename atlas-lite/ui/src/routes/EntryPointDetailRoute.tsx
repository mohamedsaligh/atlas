import { ArrowLeft, ExternalLink, Sparkles } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { useEntryPoint } from "@/api/hooks";
import { CodeBlock } from "@/components/code/CodeBlock";
import { EdgeTable } from "@/components/entry-points/EdgeTable";
import { ScopeChip } from "@/components/scope/ScopeChip";
import { Badge, pctTone } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtCount, fmtPercent, shortClass } from "@/lib/format";

export function EntryPointDetailRoute() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useEntryPoint(id);

  if (error) {
    return (
      <div className="surface rounded-xl p-12 text-center">
        <h1 className="text-lg font-semibold">Couldn't load entry point</h1>
        <p className="mt-1 text-sm text-fg-muted">{error.message}</p>
      </div>
    );
  }

  if (!data || isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const className = shortClass(data.class_fqn);

  return (
    <div className="space-y-6">
      <Link
        to="/browse"
        className="inline-flex items-center gap-1.5 text-[12.5px] text-fg-muted transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to browse
      </Link>

      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight font-mono">
            {className}<span className="text-fg-muted">.</span>{data.method_name}
          </h1>
          <Badge tone={pctTone(data.resolution_percent)} className="font-mono normal-case tracking-normal">
            resolution {fmtPercent(data.resolution_percent)}
          </Badge>
          <Badge tone="muted" className="font-mono normal-case tracking-normal">
            {fmtCount(data.edge_count)} edges
          </Badge>
        </div>
        <div className="text-[12.5px] font-mono text-fg-muted">{data.class_fqn}</div>
      </header>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Signature</CardTitle>
              <CardDescription>Top-level transformation method.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <CodeBlock code={data.method_signature} lang="java" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Domain</CardTitle>
              <CardDescription>Source schema(s) → target schema.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-[12.5px] font-mono">
              {data.source_schema_ids.map((s) => (
                <div key={s} className="flex items-center gap-2 text-fg-muted">
                  <span>{s}</span>
                  <span className="text-fg-subtle">→</span>
                  <span className="text-fg">{data.target_schema_id}</span>
                </div>
              ))}
            </div>
            <div className="border-t border-border/60 pt-3">
              <div className="text-[11px] uppercase tracking-wider text-fg-subtle mb-1.5">Scope</div>
              <ScopeChip scope={data.scope} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Source location</CardTitle>
              <CardDescription>Where this method lives in the repo.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-2 text-[12.5px] font-mono">
            <div className="text-fg-muted truncate" title={data.file}>
              {data.file}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-fg-subtle">L{data.line}</span>
              {data.browse_url && (
                <a
                  href={data.browse_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-accent hover:underline"
                >
                  open
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
            <div className="border-t border-border/60 pt-2 text-fg-subtle">
              repo {data.repo_id} · pair {data.pair_id}
            </div>
          </CardContent>
        </Card>
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between">
          <div>
            <h2 className="text-base font-semibold tracking-tight">
              Field-level edges <span className="text-fg-muted">({fmtCount(data.edges.length)})</span>
            </h2>
            <p className="text-xs text-fg-subtle">
              Source path or literal expression → target. Click <code className="font-mono">L#</code> to jump to the source.
            </p>
          </div>
          <Link
            to={`/impact?schema=${encodeURIComponent(data.source_schema_ids[0] ?? "")}&path=`}
            className="inline-flex items-center gap-1.5 text-[12px] text-accent hover:underline"
          >
            <Sparkles className="h-3.5 w-3.5" />
            Run impact analysis
          </Link>
        </div>
        <EdgeTable edges={data.edges} />
      </section>

      {data.helpers.length > 0 && (
        <section>
          <div className="mb-3">
            <h2 className="text-base font-semibold tracking-tight">
              Helper logic <span className="text-fg-muted">({data.helpers.length})</span>
            </h2>
            <p className="text-xs text-fg-subtle">
              Every helper the resolver walked through, deduplicated by FQN. Bodies are verbatim,
              line-anchored to source.
            </p>
          </div>
          <div className="space-y-3">
            {data.helpers.map((h) => (
              <div key={h.fqn} className="space-y-2">
                <div className="flex items-baseline justify-between gap-2 font-mono text-[12.5px]">
                  <div className="text-fg/90 truncate">{h.fqn}</div>
                  <div className="text-fg-subtle whitespace-nowrap">
                    {h.file.split("/").at(-1)}:L{h.start_line}-L{h.end_line}
                  </div>
                </div>
                <CodeBlock
                  code={h.body}
                  lang="java"
                  caption={h.signature}
                  startLine={h.start_line}
                />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
