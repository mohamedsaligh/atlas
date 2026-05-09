/**
 * Tanstack Query hooks bound to the Atlas read API. One hook per
 * endpoint keeps the cache keys stable and the components dumb.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, buildQuery } from "./client";
import type {
  CoverageRow,
  EdgeRow,
  EntryPointDetail,
  EntryPointSummary,
  FieldRow,
  HealthResponse,
  ImpactRow,
  Page,
  SnapshotInfo,
} from "./types";

const STALE_15_MIN = 15 * 60 * 1000;

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: () => api<HealthResponse>("/health"),
    staleTime: 30 * 1000,
  });
}

export function useSnapshot() {
  return useQuery<SnapshotInfo>({
    queryKey: ["snapshot"],
    queryFn: () => api<SnapshotInfo>("/snapshot"),
    staleTime: STALE_15_MIN,
  });
}

export interface CoverageFilters {
  repo?: string;
  pair?: string;
  page?: number;
  size?: number;
}

export function useCoverage(filters: CoverageFilters = {}) {
  return useQuery<Page<CoverageRow>>({
    queryKey: ["coverage", filters],
    queryFn: () =>
      api<Page<CoverageRow>>(
        `/coverage${buildQuery({
          repo: filters.repo,
          pair: filters.pair,
          page: filters.page ?? 1,
          size: filters.size ?? 100,
        })}`,
      ),
    placeholderData: keepPreviousData,
    staleTime: STALE_15_MIN,
  });
}

export interface EntryPointFilters {
  repo?: string;
  pair?: string;
  country?: string;
  clearing?: string;
  product?: string;
  class_fqn?: string;
  page?: number;
  size?: number;
}

export function useEntryPoints(filters: EntryPointFilters = {}) {
  return useQuery<Page<EntryPointSummary>>({
    queryKey: ["entry-points", filters],
    queryFn: () =>
      api<Page<EntryPointSummary>>(
        `/entry-points${buildQuery({
          repo: filters.repo,
          pair: filters.pair,
          country: filters.country,
          clearing: filters.clearing,
          product: filters.product,
          class_fqn: filters.class_fqn,
          page: filters.page ?? 1,
          size: filters.size ?? 50,
        })}`,
      ),
    placeholderData: keepPreviousData,
    staleTime: STALE_15_MIN,
  });
}

export function useEntryPoint(id: string | undefined) {
  return useQuery<EntryPointDetail>({
    queryKey: ["entry-point", id],
    queryFn: () => api<EntryPointDetail>(`/entry-points/${encodeURIComponent(id!)}`),
    enabled: !!id,
    staleTime: STALE_15_MIN,
  });
}

export interface ImpactQuery {
  schema: string;
  path: string;
  page?: number;
  size?: number;
}

export function useImpact(q: ImpactQuery | null) {
  return useQuery<Page<ImpactRow>>({
    queryKey: ["impact", q],
    queryFn: () =>
      api<Page<ImpactRow>>(
        `/impact${buildQuery({
          schema: q!.schema,
          path: q!.path,
          page: q!.page ?? 1,
          size: q!.size ?? 200,
        })}`,
      ),
    enabled: !!q,
    placeholderData: keepPreviousData,
    staleTime: STALE_15_MIN,
  });
}

export interface FieldSearch {
  schema?: string;
  path_prefix?: string;
  business_key?: string;
  limit?: number;
}

export function useFieldSearch(query: FieldSearch | null) {
  return useQuery<FieldRow[]>({
    queryKey: ["fields", query],
    queryFn: () =>
      api<FieldRow[]>(
        `/fields${buildQuery({
          schema: query!.schema,
          path_prefix: query!.path_prefix,
          business_key: query!.business_key,
          limit: query!.limit ?? 50,
        })}`,
      ),
    enabled: !!query && (!!query.schema || !!query.path_prefix || !!query.business_key),
    staleTime: STALE_15_MIN,
  });
}

export type EntryPointEdgesPage = Page<EdgeRow>;
