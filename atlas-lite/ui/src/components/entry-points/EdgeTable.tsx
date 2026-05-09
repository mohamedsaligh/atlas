import { ArrowRight, ExternalLink } from "lucide-react";

import type { EdgeRow } from "@/api/types";
import { Badge, kindTone } from "@/components/ui/badge";
import { TBody, TableRoot, Td, Th, THead, Tr } from "@/components/ui/table";

const HELPER_TAIL_RE = /([^.]+\.[^.]+)$/;

function helperShort(fqn: string | null): string | null {
  if (!fqn) return null;
  return HELPER_TAIL_RE.exec(fqn)?.[1] ?? fqn;
}

export function EdgeTable({ edges }: { edges: EdgeRow[] }) {
  return (
    <div className="surface-raised overflow-hidden rounded-xl">
      <TableRoot>
        <THead>
          <Tr>
            <Th className="w-10 text-right">#</Th>
            <Th>Source / value</Th>
            <Th className="w-6" />
            <Th>Target</Th>
            <Th>Kind</Th>
            <Th>Helper</Th>
            <Th className="text-right">Line</Th>
          </Tr>
        </THead>
        <TBody>
          {edges.map((edge, i) => {
            const display =
              edge.source_path ?? edge.expression.replace(/\s+/g, " ").slice(0, 80);
            return (
              <Tr key={edge.id}>
                <Td className="text-right tabular-nums text-fg-subtle">{i + 1}</Td>
                <Td className="font-mono text-[12.5px] text-fg/90 max-w-[420px] truncate">
                  {display}
                </Td>
                <Td>
                  <ArrowRight className="h-3.5 w-3.5 text-fg-subtle" />
                </Td>
                <Td className="font-mono text-[12.5px] text-fg max-w-[300px] truncate">
                  {edge.target_path}
                </Td>
                <Td>
                  <Badge tone={kindTone(edge.kind)} className="normal-case tracking-normal">
                    {edge.kind}
                  </Badge>
                </Td>
                <Td className="font-mono text-[11.5px] text-fg-muted max-w-[280px] truncate">
                  {helperShort(edge.static_helper_fqn) ?? "—"}
                </Td>
                <Td className="text-right tabular-nums text-fg-muted">
                  {edge.browse_url ? (
                    <a
                      href={edge.browse_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-accent hover:underline"
                    >
                      L{edge.line}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    <span>L{edge.line}</span>
                  )}
                </Td>
              </Tr>
            );
          })}
        </TBody>
      </TableRoot>
    </div>
  );
}
