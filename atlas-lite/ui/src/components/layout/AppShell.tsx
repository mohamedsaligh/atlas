import { Activity, Box, GitGraph, type LucideIcon, Search, Sparkles, Workflow } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useHealth } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/", label: "Home", icon: Activity },
  { to: "/browse", label: "Browse", icon: Workflow },
  { to: "/impact", label: "Impact", icon: Sparkles },
  { to: "/graph", label: "Graph", icon: GitGraph },
];

export function AppShell() {
  const health = useHealth();
  const sha = health.data?.atlas_sha?.slice(0, 12);
  const ext = health.data?.extractor_version;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1480px] items-center gap-6 px-6">
          <NavLink to="/" className="group flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-md bg-gradient-to-br from-accent/30 to-accent/5 ring-1 ring-accent/30">
              <Box className="h-4 w-4 text-accent" strokeWidth={2.4} />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight">Atlas</div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-fg-subtle">
                field lineage
              </div>
            </div>
          </NavLink>

          <nav className="flex items-center gap-1">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  cn(
                    "group flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium",
                    "transition-colors duration-150",
                    isActive
                      ? "bg-bg-subtle text-fg"
                      : "text-fg-muted hover:bg-bg-subtle hover:text-fg",
                  )
                }
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {sha && (
              <Badge tone="muted" className="font-mono normal-case tracking-normal">
                <Search className="h-3 w-3" />
                {sha}
              </Badge>
            )}
            {ext && (
              <Badge tone="muted" className="font-mono normal-case tracking-normal">
                v{ext}
              </Badge>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1480px] flex-1 px-6 py-8 animate-fade-in">
        <Outlet />
      </main>

      <footer className="mt-auto border-t border-border/60 bg-bg/60 py-4 text-center text-[11px] text-fg-subtle">
        Atlas — deterministic field-level lineage · the data here is read-only and rebuilt on every extract.
      </footer>
    </div>
  );
}
