/** UI-side formatters. Keep one source of truth so renderings agree. */

export function fmtPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(2)}%`;
}

export function fmtCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined).format(value);
}

export function fmtScopeChip(name: string | null | undefined): string {
  return name && name.length > 0 ? name : "COMMON";
}

export function shortClass(fqn: string): string {
  return fqn.split(".").at(-1) ?? fqn;
}

/** Ellipsis-truncate from the *front* — keeps the meaningful tail. */
export function truncateFromStart(s: string, max: number): string {
  return s.length <= max ? s : `…${s.slice(s.length - max + 1)}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
