/**
 * Response shapes mirrored from the FastAPI backend's OpenAPI document
 * (atlas.api.models.*). Keep this file in sync — there is one source of
 * truth (the API), and these types describe what the wire produces.
 */

export interface Scope {
  common: boolean;
  country: string | null;
  clearing: string | null;
  product: string | null;
  field_group: string | null;
}

export interface Page<T> {
  items: T[];
  page: number;
  size: number;
  total: number;
}

export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail: string | null;
  instance: string | null;
}

export interface HealthResponse {
  status: string;
  atlas_sha: string | null;
  extractor_version: string | null;
  snapshot_built_at: string | null;
}

export interface SnapshotInfo {
  atlas_sha: string;
  built_at: string;
  extractor_version: string;
  edge_count: number;
  mapper_count: number;
  field_count: number;
  test_count: number;
}

export interface CoverageRow {
  repo_id: string;
  pair_id: string;
  target_field_count: number | null;
  coverage_percent: number | null;
  edges_emitted: number;
  files_scanned: number;
  mappers_detected: number;
  unmatched: string[];
}

export interface EntryPointSummary {
  id: string;
  pair_id: string;
  repo_id: string;
  class_fqn: string;
  method_name: string;
  method_signature: string;
  source_schema_ids: string[];
  target_schema_id: string;
  file: string;
  line: number;
  sha: string;
  browse_url: string | null;
  scope: Scope;
  edge_count: number;
  resolution_percent: number | null;
}

export interface EdgeRow {
  id: string;
  pair_id: string;
  mapper_id: string;
  entry_point_id: string | null;
  kind: EdgeKind;
  expression: string;
  source_schema_id: string | null;
  source_path: string | null;
  target_schema_id: string;
  target_path: string;
  static_helper_fqn: string | null;
  file: string;
  line: number;
  browse_url: string | null;
}

export type EdgeKind =
  | "rename"
  | "constant"
  | "format"
  | "expression"
  | "concat"
  | "qualifier"
  | "static_call"
  | "enrichment"
  | "construction"
  | "intra_class"
  | "unmapped";

export interface HelperBody {
  fqn: string;
  file: string;
  start_line: number;
  end_line: number;
  signature: string;
  body: string;
  body_sha256: string;
}

export interface EntryPointDetail extends EntryPointSummary {
  edges: EdgeRow[];
  helpers: HelperBody[];
}

export interface ImpactRow {
  entry_point_id: string | null;
  class_fqn: string | null;
  method_name: string | null;
  scope: Scope;
  edge_id: string;
  kind: EdgeKind;
  helper: string | null;
  source_schema_id: string;
  source_path: string;
  target_schema_id: string;
  target_path: string;
  line: number;
  browse_url: string | null;
}

export interface FieldRow {
  id: string;
  schema_id: string;
  path: string;
  business_key: string | null;
  type: string | null;
}
