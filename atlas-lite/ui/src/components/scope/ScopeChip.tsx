import { Badge } from "@/components/ui/badge";
import type { Scope } from "@/api/types";
import { fmtScopeChip } from "@/lib/format";

export function ScopeChip({ scope, dense = false }: { scope: Scope; dense?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {!dense || scope.country ? (
        <Badge tone="neutral" className="font-mono">
          {fmtScopeChip(scope.country)}
        </Badge>
      ) : null}
      {!dense || scope.clearing ? (
        <Badge tone="neutral" className="font-mono">
          {fmtScopeChip(scope.clearing)}
        </Badge>
      ) : null}
      {!dense || scope.product ? (
        <Badge tone="neutral" className="font-mono">
          {fmtScopeChip(scope.product)}
        </Badge>
      ) : null}
      {scope.field_group && (
        <Badge tone="muted" className="font-mono">
          {scope.field_group}
        </Badge>
      )}
    </div>
  );
}
