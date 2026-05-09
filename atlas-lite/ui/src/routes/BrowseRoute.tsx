import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useEntryPoints } from "@/api/hooks";
import { EntryPointTable } from "@/components/entry-points/EntryPointTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const FILTER_KEYS = ["country", "clearing", "product", "repo", "pair", "class_fqn"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

export function BrowseRoute() {
  const [params, setParams] = useSearchParams();
  const [classQuery, setClassQuery] = useState(params.get("class_fqn") ?? "");

  const filters = useMemo(() => {
    const out: Record<FilterKey, string | undefined> = {} as Record<FilterKey, string | undefined>;
    for (const k of FILTER_KEYS) {
      const v = params.get(k);
      out[k] = v && v.length > 0 ? v : undefined;
    }
    return out;
  }, [params]);

  const page = Number(params.get("page") ?? "1");
  const size = 50;

  const { data, isLoading, isFetching } = useEntryPoints({
    ...filters,
    page,
    size,
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;

  function setParam(key: string, value: string | undefined) {
    const next = new URLSearchParams(params);
    if (value && value.length > 0) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  function clearAll() {
    setClassQuery("");
    setParams(new URLSearchParams(), { replace: true });
  }

  const activeChips = FILTER_KEYS.filter((k) => filters[k]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Browse entry points</h1>
        <p className="text-sm text-fg-muted">
          {data ? `${data.total.toLocaleString()} method(s) match` : "Filter by scope or class FQN."}
        </p>
      </header>

      <Card>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-12">
          <FilterInput
            label="Country"
            value={filters.country ?? ""}
            placeholder="e.g. AR"
            onCommit={(v) => setParam("country", v)}
            className="md:col-span-2"
          />
          <FilterInput
            label="Clearing"
            value={filters.clearing ?? ""}
            placeholder="e.g. COELSA"
            onCommit={(v) => setParam("clearing", v)}
            className="md:col-span-2"
          />
          <FilterInput
            label="Product"
            value={filters.product ?? ""}
            placeholder="e.g. SG_FAST"
            onCommit={(v) => setParam("product", v)}
            className="md:col-span-2"
          />
          <FilterInput
            label="Repo"
            value={filters.repo ?? ""}
            placeholder="repo_id"
            onCommit={(v) => setParam("repo", v)}
            className="md:col-span-2"
          />
          <FilterInput
            label="Pair"
            value={filters.pair ?? ""}
            placeholder="pair_id"
            onCommit={(v) => setParam("pair", v)}
            className="md:col-span-2"
          />
          <div className="md:col-span-2 flex flex-col gap-1.5">
            <label className="text-[11px] uppercase tracking-wider text-fg-subtle">
              Class FQN
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
              <Input
                value={classQuery}
                onChange={(e) => setClassQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setParam("class_fqn", classQuery);
                }}
                onBlur={() => setParam("class_fqn", classQuery)}
                placeholder="com.x.payment..."
                className="pl-8 font-mono text-[12.5px]"
              />
            </div>
          </div>
        </CardContent>

        {activeChips.length > 0 && (
          <div className="flex items-center gap-2 border-t border-border/60 px-5 py-2.5 text-[11px] text-fg-subtle">
            <span>Active:</span>
            <div className="flex flex-wrap gap-1.5">
              {activeChips.map((k) => (
                <button
                  key={k}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-bg-subtle px-2 py-0.5 font-mono text-[11px] text-fg/90 transition-colors hover:bg-bg-raised"
                  onClick={() => setParam(k, undefined)}
                >
                  {k}={filters[k]}
                  <X className="h-3 w-3" />
                </button>
              ))}
            </div>
            <Button intent="ghost" size="sm" onClick={clearAll} className="ml-auto h-6">
              Clear all
            </Button>
          </div>
        )}
      </Card>

      <EntryPointTable rows={data?.items ?? []} loading={isLoading || isFetching} />

      {data && totalPages > 1 && (
        <div className="flex items-center justify-between text-[12px] text-fg-muted">
          <div>
            Page <span className="text-fg">{page}</span> of {totalPages.toLocaleString()}
          </div>
          <div className="flex gap-2">
            <Button
              intent="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setParam("page", String(page - 1))}
            >
              Previous
            </Button>
            <Button
              intent="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setParam("page", String(page + 1))}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FilterInput({
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
  // Keep draft in sync when route navigation changes the URL externally.
  if (draft !== value && document.activeElement?.tagName !== "INPUT") {
    setDraft(value);
  }
  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <label className="text-[11px] uppercase tracking-wider text-fg-subtle">{label}</label>
      <Input
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onCommit(draft || undefined);
        }}
        onBlur={() => onCommit(draft || undefined)}
        className="font-mono text-[12.5px]"
      />
    </div>
  );
}
