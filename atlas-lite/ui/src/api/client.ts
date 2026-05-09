/**
 * Minimal fetch wrapper with shared error handling. The Vite dev server
 * proxies /api → ATLAS API at the configured target, so the same paths
 * work in dev and prod without origin gymnastics.
 */

import type { ProblemDetail } from "./types";

const PREFIX = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetail | null;

  constructor(message: string, status: number, problem: ProblemDetail | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${PREFIX}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    let problem: ProblemDetail | null = null;
    try {
      problem = (await response.json()) as ProblemDetail;
    } catch {
      // body wasn't JSON — fall through with status only
    }
    throw new ApiError(
      problem?.title ?? `request failed with status ${response.status}`,
      response.status,
      problem,
    );
  }
  return (await response.json()) as T;
}

export function buildQuery(params: Record<string, string | number | boolean | null | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}
