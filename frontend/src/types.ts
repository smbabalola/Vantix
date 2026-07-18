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

