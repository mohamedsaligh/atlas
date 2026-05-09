import { Layers, Search, Sparkles, Workflow, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useGraph } from "@/api/hooks";
import type { GraphLink, GraphNode, GraphResponse } from "@/api/graph-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtCount } from "@/lib/format";

const ForceGraph = lazy(() => import("@/components/graph/ForceGraph"));

const FILTER_KEYS = ["country", "clearing", "product", "class_fqn"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

export function GraphRoute() {
  const [params, setParams] = useSearchParams();

  const filters = useMemo(() => {
    const out: Record<FilterKey, string | undefined> = {} as Record<FilterKey, string | undefined>;
    for (const k of FILTER_KEYS) {
      const v = params.get(k);
      out[k] = v && v.length > 0 ? v : undefined;
    }
    return out;
  }, [params]);

  const limit = Number(params.get("limit") ?? "800");
  const search = params.get("q") ?? "";

  const { data, isLoading, error } = useGraph({ ...filters, limit }, true);

  const handleSetParam = useCallback(
    (key: string, value: string | undefined) => {
      const next = new URLSearchParams(params);
      if (value && value.length > 0) next.set(key, value);
      else next.delete(key);
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Workflow className="h-6 w-6 text-accent" />
            Lineage graph
          </h1>
          <p className="mt-1 text-sm text-fg-muted">
            Force-directed view. Each entry point is a node; its source / target fields fan out from it.
            Filter by scope to bring the picture down to a single product or country.
          </p>
        </div>
        {data && (
          <div className="flex items-center gap-2 text-[12px] text-fg-muted">
            <Badge tone="muted" className="font-mono normal-case tracking-normal">
              {fmtCount(data.nodes.length)} nodes
            </Badge>
            <Badge tone="muted" className="font-mono normal-case tracking-normal">
              {fmtCount(data.links.length)} links
            </Badge>
            {data.truncated && (
              <Badge tone="warn" className="normal-case tracking-normal">
                truncated — narrow scope
              </Badge>
            )}
          </div>
        )}
      </header>

      <Card>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-12">
          <FilterField
            label="Country"
            value={filters.country ?? ""}
            placeholder="AR"
            onCommit={(v) => handleSetParam("country", v)}
            className="md:col-span-2"
          />
          <FilterField
            label="Clearing"
            value={filters.clearing ?? ""}
            placeholder="COELSA"
            onCommit={(v) => handleSetParam("clearing", v)}
            className="md:col-span-2"
          />
          <FilterField
            label="Product"
            value={filters.product ?? ""}
            placeholder="SG_FAST"
            onCommit={(v) => handleSetParam("product", v)}
            className="md:col-span-2"
          />
          <FilterField
            label="Class FQN"
            value={filters.class_fqn ?? ""}
            placeholder="com.x.payment..."
            onCommit={(v) => handleSetParam("class_fqn", v)}
            className="md:col-span-3"
          />
          <div className="md:col-span-3 flex flex-col gap-1.5">
            <label className="text-[11px] uppercase tracking-wider text-fg-subtle">Highlight</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
              <Input
                value={search}
                placeholder="ledger.iban, agent..."
                onChange={(e) => handleSetParam("q", e.target.value || undefined)}
                className="pl-8 font-mono text-[12.5px]"
              />
              {search && (
                <button
                  className="absolute right-1 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center text-fg-subtle hover:text-fg"
                  onClick={() => handleSetParam("q", undefined)}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="relative h-[640px] overflow-hidden p-0">
        {isLoading && (
          <div className="absolute inset-0 grid place-items-center">
            <div className="space-y-2 text-center">
              <Skeleton className="mx-auto h-6 w-40" />
              <p className="text-[12px] text-fg-subtle">Building graph…</p>
            </div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 grid place-items-center text-sm text-danger">
            {error.message}
          </div>
        )}
        {!isLoading && !error && data && (data.nodes.length === 0) && (
          <div className="absolute inset-0 grid place-items-center text-sm text-fg-muted">
            <div className="space-y-2 text-center">
              <Sparkles className="mx-auto h-6 w-6 text-fg-subtle" />
              <p>No entry points match these filters.</p>
            </div>
          </div>
        )}
        {!isLoading && !error && data && data.nodes.length > 0 && (
          <Suspense fallback={null}>
            <ForceGraph data={data} highlight={search} />
          </Suspense>
        )}
      </Card>

      <Legend />
    </div>
  );
}

function FilterField({
  label,
  value,
  placeholder,
  onCommit,
  className,
}: {
  label: string;
  value: string;
  placeholder: string;
  onCommit: (next: string | undefined) => void;
  className?: string;
}) {
  const [draft, setDraft] = useState(value);
  const lastValue = useRef(value);
  useEffect(() => {
    if (value !== lastValue.current) {
      setDraft(value);
      lastValue.current = value;
    }
  }, [value]);
  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <label className="text-[11px] uppercase tracking-wider text-fg-subtle">{label}</label>
      <Input
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onCommit(draft || undefined)}
        onBlur={() => onCommit(draft || undefined)}
        className="font-mono text-[12.5px]"
      />
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 text-[11px] text-fg-muted">
      <Layers className="h-3 w-3" />
      <span>Legend:</span>
      <Badge tone="accent" className="normal-case tracking-normal">
        entry point
      </Badge>
      <Badge tone="success" className="normal-case tracking-normal">
        source field
      </Badge>
      <Badge tone="warn" className="normal-case tracking-normal">
        target field
      </Badge>
      <span className="ml-2">·</span>
      <span>Drag to rotate · scroll to zoom · click a node to focus.</span>
    </div>
  );
}

export type { GraphLink, GraphNode, GraphResponse };

// Re-export the inner Button so the lazy chunk is co-located.
export { Button };
