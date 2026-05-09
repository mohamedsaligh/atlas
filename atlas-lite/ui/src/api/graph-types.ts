/** Graph endpoint response shape. */

export type GraphNodeKind = "entry_point" | "field" | "schema";
export type GraphLinkKind = "reads" | "writes" | "spans";

export interface GraphNode {
  id: string;
  label: string;
  kind: GraphNodeKind;
  schema_id?: string | null;
  country?: string | null;
  clearing?: string | null;
  product?: string | null;
  edge_count?: number | null;
  resolution_percent?: number | null;
}

export interface GraphLink {
  source: string;
  target: string;
  kind: GraphLinkKind;
}

export interface GraphResponse {
  nodes: GraphNode[];
  links: GraphLink[];
  truncated: boolean;
}
