export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Evidence {
  file: string;
  line: number;
  statement: string;
  reference_kind: string;
}

export interface ImpactedObject {
  object_key: string;
  object_type: string;
  object_type_label: string;
  description: string;
  hops: number;
  path: string[];
  evidence: Evidence;
}

export interface BlindSpot {
  object_key: string;
  file: string;
  line: number;
  reason: string;
}

export interface ImpactReport {
  workspace: string;
  changed_objects: string[];
  not_found: string[];
  severity: Severity;
  severity_reasons: string[];
  impacted_count: number;
  impacted: ImpactedObject[];
  truncated: boolean;
  external_contracts: string[];
  regression_scope: string[];
  blind_spots: BlindSpot[];
  resolved_from_prompt: { object_key: string; score: number; matched_because: string }[];
  changed_files: { status: string; path: string }[];
}

export interface Hotspot {
  object_key: string;
  object_type_label: string;
  description: string;
  dependents: number;
  blind_spots: number;
}

export interface Dashboard {
  workspace: string;
  ready: boolean;
  indexing: boolean;
  indexed_at: string;
  objects: number;
  references: number;
  unresolved: number;
  blind_spot_objects: number;
  blind_spot_total: number;
  type_breakdown: { type: string; label: string; count: number }[];
  hotspots: Hotspot[];
  recent_commits: { commit: string; author: string; date: string; subject: string }[];
  external_contract_objects: number;
}

export interface DiffLine {
  kind: "add" | "del" | "ctx";
  new: number | null;
  old: number | null;
  text: string;
}

export interface Annotation {
  line: number;
  label: string;
  severity: "high" | "medium" | "info" | "blind";
  detail: string;
}

export interface ReviewFile {
  path: string;
  status: string;
  object_key: string;
  object_type_label: string;
  description: string;
  added: number;
  removed: number;
  dependents: {
    object_key: string;
    object_type_label: string;
    reference_kind: string;
    file: string;
    line: number;
    statement: string;
  }[];
  annotations: Annotation[];
  hunks: { header: string; old_start: number; new_start: number; lines: DiffLine[] }[];
}

export interface ReviewPayload {
  workspace: string;
  revision_range: string;
  impact: ImpactReport;
  files: ReviewFile[];
}

export interface WorkspaceInfo {
  id: string;
  kind: string;
  description: string;
  ready: boolean;
  indexing: boolean;
  indexed_at: string;
  last_error: string;
  objects: number;
  references: number;
  unresolved: number;
  blind_spot_objects: number;
}

export interface ObjectSummary {
  object_key: string;
  object_type: string;
  object_type_label: string;
  name: string;
  description: string;
  files: string[];
  tags: string[];
  direct_dependents: number;
}

export interface WhereUsed {
  workspace: string;
  object: ObjectSummary;
  used_by: ImpactedObject[];
  uses: string[];
}
