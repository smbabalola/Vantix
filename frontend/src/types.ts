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
  unit: "m" | "ft";
  provenance: "entered";
}

export interface BasicInterval {
  id: string;
  name: string;
  operation_mode: "drilling" | "completion" | "workover";
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
  validated_version: number;
  draft_checksum: string;
  issues: Array<{ code: string; field: string; message: string; severity: string }>;
}

export type ProductUnitCode = "kg" | "t" | "lb" | "L" | "m3" | "gal_us" | "bbl" | "each" | "package";
export type PackageContentUnitCode = Exclude<ProductUnitCode, "package">;
export type PackagingType = "sack" | "pail" | "drum" | "tote" | "bulk" | "case" | "each" | "other";

export interface ProductPrice {
  id: string;
  project_product_id: string;
  effective_from: string;
  effective_to: string | null;
  unit_price: string;
  currency: string;
  price_basis_unit_code: ProductUnitCode;
  source: string | null;
}

export interface ProjectProduct {
  id: string;
  product_definition_id: string;
  project_id: string;
  configuration_version_id: string;
  configuration_row_version: number;
  item_code: string;
  item_name: string;
  alternate_name: string | null;
  packaging: PackagingType;
  package_size: string;
  package_unit_code: PackageContentUnitCode;
  inventory_applicable: boolean;
  inventory_unit_code: ProductUnitCode | null;
  specific_gravity: string | null;
  active: boolean;
  prices: ProductPrice[];
}

export interface OpeningStockAuthorityProduct {
  product_definition_id: string;
  configuration_product_version_id: string;
  item_code: string;
  item_name: string;
  package_size: string;
  package_unit_code: PackageContentUnitCode;
  inventory_unit_code: ProductUnitCode;
  price: ProductPrice | null;
  opened_by_posting_id: string | null;
}

export interface OpeningStockAuthority {
  project_id: string;
  posting_date: string;
  configuration_snapshot_id: string;
  products: OpeningStockAuthorityProduct[];
}

export interface InventoryLedgerLine {
  id: string;
  product_definition_id: string;
  configuration_product_version_id: string;
  product_price_version_id: string | null;
  entered_quantity: string;
  entered_unit_code: ProductUnitCode;
  canonical_signed_quantity: string;
  canonical_unit_code: "kg" | "L" | "each";
  price_status: "ready" | "unavailable";
  applied_unit_price: string | null;
  price_basis_unit_code: ProductUnitCode | null;
  price_effective_from: string | null;
  price_effective_to: string | null;
  currency: string | null;
  currency_minor_unit_scale: number | null;
  posted_line_amount: string | null;
  frozen_product: Record<string, unknown>;
}

export interface OpeningStockPreviewLine {
  product_definition_id: string;
  configuration_product_version_id: string;
  item_code: string;
  item_name: string;
  entered_quantity: string;
  entered_unit_code: ProductUnitCode;
  package_size: string;
  package_unit_code: PackageContentUnitCode;
  canonical_quantity: string;
  canonical_unit_code: "kg" | "L" | "each";
  package_count: string;
  price_status: "ready" | "unavailable";
  applied_unit_price: string | null;
  price_basis_unit_code: ProductUnitCode | null;
  price_effective_from: string | null;
  price_effective_to: string | null;
  currency: string | null;
  currency_minor_unit_scale: number | null;
  line_amount: string | null;
}

export interface OpeningStockPreview {
  project_id: string;
  posting_date: string;
  configuration_snapshot_id: string;
  lines: OpeningStockPreviewLine[];
  currencies: Record<string, string>;
}

export interface InventoryPosting {
  id: string;
  project_id: string;
  source_configuration_snapshot_id: string;
  posting_type: "opening_stock" | "reversal";
  status: "posted";
  posting_date: string;
  reversal_of_posting_id: string | null;
  reversal_posting_id: string | null;
  reason: string | null;
  posted_by: string;
  posted_at: string;
  lines: InventoryLedgerLine[];
}

