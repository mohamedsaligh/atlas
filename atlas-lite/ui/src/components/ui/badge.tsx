import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const badge = cva(
  [
    "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5",
    "text-[11px] font-medium uppercase tracking-wider whitespace-nowrap",
    "transition-colors duration-150",
  ],
  {
    variants: {
      tone: {
        neutral: "border-border bg-bg-subtle text-fg-muted",
        accent: "border-accent/40 bg-accent/10 text-accent",
        success: "border-success/40 bg-success/10 text-success",
        warn: "border-warn/40 bg-warn/10 text-warn",
        danger: "border-danger/40 bg-danger/10 text-danger",
        muted: "border-border bg-transparent text-fg-subtle",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, tone, ...rest }, ref) => (
    <span ref={ref} className={cn(badge({ tone }), className)} {...rest} />
  ),
);
Badge.displayName = "Badge";

/** Picks a tone for an edge `kind` so palette stays consistent across views. */
export function kindTone(
  kind: string,
): "neutral" | "accent" | "success" | "warn" | "danger" | "muted" {
  switch (kind) {
    case "rename":
      return "neutral";
    case "qualifier":
    case "static_call":
    case "intra_class":
      return "accent";
    case "constant":
    case "construction":
      return "muted";
    case "expression":
    case "format":
    case "concat":
      return "warn";
    case "enrichment":
      return "success";
    case "unmapped":
      return "danger";
    default:
      return "neutral";
  }
}

/** Resolution / coverage % → tone bucket. Keeps colour story consistent. */
export function pctTone(value: number | null | undefined): "success" | "warn" | "danger" | "muted" {
  if (value === null || value === undefined) return "muted";
  if (value >= 90) return "success";
  if (value >= 70) return "warn";
  return "danger";
}
