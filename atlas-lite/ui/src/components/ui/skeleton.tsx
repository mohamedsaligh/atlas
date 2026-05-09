import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-bg-subtle",
        "before:absolute before:inset-0 before:gpu",
        "before:bg-gradient-to-r before:from-transparent before:via-fg/[0.06] before:to-transparent",
        "before:animate-shimmer",
        className,
      )}
    />
  );
}
