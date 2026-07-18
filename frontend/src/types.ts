export type RevisionState =
  | "draft"
  | "ready_for_review"
  | "submitted"
  | "rejected"
  | "approved"
  | "superseded";

export interface GeneralSection {
  operation_mode: string;
  interval_id: string;
  fluid_system_id: string;
  present_activity: string;
}

export interface Revision {
  id: string;
  number: number;
  kind: string;
  state: RevisionState;
  version: number;
  data: { general?: GeneralSection };
  checksum: string | null;
  based_on_revision_id: string | null;
}

export interface Report {
  id: string;
  project_id: string;
  report_date: string;
  report_number: string;
  revision: Revision;
}

export interface ReadinessIssue {
  code: string;
  section: string;
  field: string | null;
  message: string;
  blocking: boolean;
}

export interface Readiness {
  state: string;
  can_submit: boolean;
  issues: ReadinessIssue[];
}

export type SaveState = "Saved" | "Saving" | "Offline draft" | "Sync pending" | "Conflict" | "Failed";

export interface Project {
  id: string;
  organisation_id: string;
  project_code: string;
  project_name: string;
  well_name: string;
  time_zone: string;
  currency: string;
  unit_set: string;
  status: string;
  current_configuration_version_id: string | null;
  active_configuration_snapshot_id: string | null;
}

export interface EnteredDepth {
  value: string;
  unit: string;
  provenance: "entered";
}

export interface BasicInterval {
  id: string;
  name: string;
  operation_mode: string;
  top_md?: EnteredDepth;
  bottom_md?: EnteredDepth;
}

export interface ProjectConfiguration {
  id: string;
  project_id: string;
  version: number;
  state: "draft" | "active" | "superseded";
  row_version: number;
  data: { default_interval_id: string | null; intervals: BasicInterval[] };
  change_summary: string | null;
  snapshot_id: string | null;
  checksum: string | null;
}

export interface ConfigurationReadiness {
  state: "ready" | "incomplete";
  can_activate: boolean;
  issues: Array<{ code: string; field: string; message: string; severity: string }>;
}

