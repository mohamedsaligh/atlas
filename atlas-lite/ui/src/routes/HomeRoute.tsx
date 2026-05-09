import { Activity, ArrowUpRight, Layers, ScanLine } from "lucide-react";
import { Link } from "react-router-dom";

import { useCoverage, useEntryPoints, useSnapshot } from "@/api/hooks";
import { EntryPointTable } from "@/components/entry-points/EntryPointTable";
import { Badge, pctTone } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtCount, fmtPercent } from "@/lib/format";

export function HomeRoute() {
  const snapshot = useSnapshot();
  const coverage = useCoverage({ size: 200 });
  const top = useEntryPoints({ size: 8 });

  const avgCoverage =
    coverage.data?.items?.length
      ? coverage.data.items.reduce((acc, c) => acc + (c.coverage_percent ?? 0), 0) /
        coverage.data.items.length
      : null;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Field-level lineage at a glance
        </h1>
        <p className="mt-1 text-sm text-fg-muted">
          Every transformation entry point Atlas extracted from the configured repos. Drill into a
          method to see its edges and the actual helper logic behind every mapping.
        </p>
      </header>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat
          icon={<Layers className="h-4 w-4 text-accent" />}
          label="Entry points"
          value={fmtCount(top.data?.total)}
          loading={top.isLoading}
        />
        <Stat
          icon={<ScanLine className="h-4 w-4 text-accent" />}
          label="Edges"
          value={fmtCount(snapshot.data?.edge_count)}
          loading={snapshot.isLoading}
          hint={snapshot.data ? `${fmtCount(snapshot.data.mapper_count)} mappers · ${fmtCount(snapshot.data.field_count)} fields` : undefined}
        />
        <Stat
          icon={<Activity className="h-4 w-4 text-accent" />}
          label="Mean pair coverage"
          value={fmtPercent(avgCoverage)}
          loading={coverage.isLoading}
          tone={pctTone(avgCoverage)}
        />
      </section>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Top entry points by edge count</CardTitle>
                <CardDescription>
                  The biggest transformation surfaces — review here before refactoring.
                </CardDescription>
              </div>
              <Link
                to="/browse"
                className="text-[12px] text-accent inline-flex items-center gap-1 hover:underline"
              >
                Browse all
                <ArrowUpRight className="h-3 w-3" />
              </Link>
            </CardHeader>
            <CardContent className="p-0">
              <EntryPointTable rows={top.data?.items ?? []} loading={top.isLoading} />
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Coverage outliers</CardTitle>
              <CardDescription>Pairs whose target schema isn't fully covered.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {coverage.isLoading && (
              <div className="space-y-2">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
              </div>
            )}
            {(coverage.data?.items ?? [])
              .slice()
              .sort((a, b) => (a.coverage_percent ?? 0) - (b.coverage_percent ?? 0))
              .slice(0, 6)
              .map((c) => (
                <div
                  key={`${c.repo_id}:${c.pair_id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/60 bg-bg-subtle/40 px-3 py-2 text-sm transition-colors duration-150 hover:bg-bg-subtle"
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[12.5px] truncate">{c.pair_id}</div>
                    <div className="text-[11px] text-fg-subtle truncate">{c.repo_id}</div>
                  </div>
                  <Badge tone={pctTone(c.coverage_percent)} className="font-mono normal-case tracking-normal">
                    {fmtPercent(c.coverage_percent)}
                  </Badge>
                </div>
              ))}
            {!coverage.isLoading && (coverage.data?.items.length ?? 0) === 0 && (
              <div className="text-sm text-fg-subtle">No coverage data yet.</div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  hint,
  loading,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  loading?: boolean;
  tone?: "success" | "warn" | "danger" | "muted";
}) {
  return (
    <Card className="animate-scale-in">
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-fg-subtle">
          {icon}
          {label}
        </div>
        {loading ? (
          <Skeleton className="h-8 w-2/3" />
        ) : (
          <div className="flex items-end gap-2">
            <div className="text-3xl font-semibold tracking-tight tabular-nums">{value}</div>
            {tone && (
              <Badge tone={tone} className="normal-case tracking-normal">
                {tone === "success" ? "good" : tone === "warn" ? "watch" : tone === "danger" ? "low" : "—"}
              </Badge>
            )}
          </div>
        )}
        {hint && <div className="text-[11px] text-fg-subtle">{hint}</div>}
      </CardContent>
    </Card>
  );
}
