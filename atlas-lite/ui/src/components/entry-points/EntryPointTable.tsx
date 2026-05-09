import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { EntryPointSummary } from "@/api/types";
import { ScopeChip } from "@/components/scope/ScopeChip";
import { Badge, pctTone } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TBody, TableRoot, Td, Th, THead, Tr } from "@/components/ui/table";
import { fmtCount, fmtPercent, shortClass } from "@/lib/format";

export function EntryPointTable({
  rows,
  loading,
  empty,
}: {
  rows: EntryPointSummary[];
  loading?: boolean;
  empty?: string;
}) {
  const nav = useNavigate();

  return (
    <div className="surface-raised overflow-hidden rounded-xl">
      <TableRoot>
        <THead>
          <Tr>
            <Th>Class</Th>
            <Th>Method</Th>
            <Th className="text-right">Edges</Th>
            <Th className="text-right">Resolution</Th>
            <Th>Scope</Th>
            <Th>Sources → Target</Th>
            <Th className="w-8" />
          </Tr>
        </THead>
        <TBody>
          {loading
            ? Array.from({ length: 8 }).map((_, i) => (
                <Tr key={i}>
                  <Td colSpan={7}>
                    <Skeleton className="h-5 w-full" />
                  </Td>
                </Tr>
              ))
            : rows.map((ep) => (
                <Tr
                  key={ep.id}
                  onClick={() => nav(`/entry-points/${encodeURIComponent(ep.id)}`)}
                  className="cursor-pointer"
                >
                  <Td className="font-mono text-[12.5px] text-fg/90 max-w-[260px] truncate">
                    {shortClass(ep.class_fqn)}
                  </Td>
                  <Td className="font-mono text-[12.5px]">{ep.method_name}</Td>
                  <Td className="text-right tabular-nums text-fg-muted">{fmtCount(ep.edge_count)}</Td>
                  <Td className="text-right">
                    <Badge tone={pctTone(ep.resolution_percent)} className="font-mono normal-case tracking-normal">
                      {fmtPercent(ep.resolution_percent)}
                    </Badge>
                  </Td>
                  <Td>
                    <ScopeChip scope={ep.scope} dense />
                  </Td>
                  <Td className="font-mono text-[11.5px] text-fg-muted max-w-[280px] truncate">
                    {ep.source_schema_ids.join(", ")} → {ep.target_schema_id}
                  </Td>
                  <Td>
                    <ChevronRight className="h-4 w-4 text-fg-subtle transition-transform duration-150 group-hover:translate-x-0.5" />
                  </Td>
                </Tr>
              ))}
        </TBody>
      </TableRoot>
      {!loading && rows.length === 0 && (
        <div className="px-5 py-12 text-center text-sm text-fg-subtle">
          {empty ?? "No entry points match the current filters."}
        </div>
      )}
    </div>
  );
}
