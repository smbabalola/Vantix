from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrganisationView(BaseModel):
    id: UUID
    name: str


class ProjectCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=50)
    project_name: str = Field(min_length=1, max_length=200)
    well_name: str = Field(min_length=1, max_length=200)
    operator_name: str | None = Field(default=None, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    rig_name: str | None = Field(default=None, max_length=200)
    location_text: str | None = Field(default=None, max_length=500)
    time_zone: str
    currency: str = Field(min_length=3, max_length=3)
    unit_set: Literal["Metric", "Field"]
    reporting_start_date: date | None = None


class ProjectView(ProjectCreate):
    id: UUID
    organisation_id: UUID
    status: str = "draft"
    row_version: int = 1
    current_configuration_version_id: UUID | None = None
    active_configuration_snapshot_id: UUID | None = None


class UnitValue(BaseModel):
    value: str
    unit: Literal["m", "ft"]
    provenance: Literal["entered"] = "entered"


class BasicInterval(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=200)
    operation_mode: Literal["drilling", "completion", "workover"]
    top_md: UnitValue | None = None
    bottom_md: UnitValue | None = None


class ProjectConfigurationData(BaseModel):
    default_interval_id: UUID | None = None
    intervals: list[BasicInterval] = Field(default_factory=list)


class ConfigurationCreate(BaseModel):
    data: ProjectConfigurationData | None = None
    change_summary: str | None = Field(default=None, max_length=1000)
    copy_active: bool = True


class ConfigurationPatch(BaseModel):
    expected_version: int = Field(ge=1)
    data: ProjectConfigurationData
    change_summary: str | None = Field(default=None, max_length=1000)


class ConfigurationView(BaseModel):
    id: UUID
    project_id: UUID
    version: int
    state: Literal["draft", "active", "superseded"]
    row_version: int
    data: dict[str, Any]
    change_summary: str | None = None
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    snapshot_id: UUID | None = None
    checksum: str | None = None


class ConfigurationReadinessView(BaseModel):
    state: Literal["ready", "incomplete"]
    can_activate: bool
    validated_version: int
    draft_checksum: str
    issues: list[dict[str, Any]]


class ConfigurationActivation(BaseModel):
    expected_version: int = Field(ge=1)
    expected_checksum: str = Field(min_length=64, max_length=64)


ProductUnitCode = Literal["kg", "t", "lb", "L", "m3", "gal_us", "bbl", "each", "package"]
PackageContentUnitCode = Literal["kg", "t", "lb", "L", "m3", "gal_us", "bbl", "each"]
PackagingType = Literal["sack", "pail", "drum", "tote", "bulk", "case", "each", "other"]


class ProjectProductFields(BaseModel):
    item_code: str = Field(min_length=1, max_length=100)
    item_name: str = Field(min_length=1, max_length=200)
    alternate_name: str | None = Field(default=None, max_length=200)
    packaging: PackagingType
    package_size: str
    package_unit_code: PackageContentUnitCode
    inventory_applicable: bool
    inventory_unit_code: ProductUnitCode | None = None
    specific_gravity: str | None = None
    active: bool = True


class ProjectProductCreate(ProjectProductFields):
    configuration_version_id: UUID
    expected_configuration_version: int = Field(ge=1)


class ProjectProductPatch(ProjectProductFields):
    expected_configuration_version: int = Field(ge=1)


class ConfigurationVersionExpectation(BaseModel):
    expected_configuration_version: int = Field(ge=1)


class ConfigurationMutationView(BaseModel):
    configuration_row_version: int


class ProductPriceFields(BaseModel):
    effective_from: date
    effective_to: date | None = None
    unit_price: str
    currency: str = Field(min_length=3, max_length=3)
    price_basis_unit_code: ProductUnitCode
    source: str | None = Field(default=None, max_length=200)


class ProductPriceCreate(ProductPriceFields):
    expected_configuration_version: int = Field(ge=1)


class ProductPricePatch(ProductPriceFields):
    expected_configuration_version: int = Field(ge=1)


class ProductPriceView(ProductPriceFields):
    id: UUID
    project_product_id: UUID


class ProjectProductView(ProjectProductFields):
    id: UUID
    product_definition_id: UUID
    project_id: UUID
    configuration_version_id: UUID
    configuration_row_version: int
    prices: list[ProductPriceView]


class OpeningStockAuthorityProduct(BaseModel):
    product_definition_id: UUID
    configuration_product_version_id: UUID
    item_code: str
    item_name: str
    package_size: str
    package_unit_code: PackageContentUnitCode
    inventory_unit_code: ProductUnitCode
    price: ProductPriceView | None


class OpeningStockAuthorityView(BaseModel):
    project_id: UUID
    posting_date: date
    configuration_snapshot_id: UUID
    products: list[OpeningStockAuthorityProduct]


class OpeningStockLineCreate(BaseModel):
    product_definition_id: UUID
    entered_quantity: str
    entered_unit_code: ProductUnitCode


class OpeningStockCreate(BaseModel):
    posting_date: date
    lines: list[OpeningStockLineCreate] = Field(min_length=1)


class InventoryReversalCreate(BaseModel):
    posting_date: date
    reason: str = Field(min_length=1, max_length=1000)


class InventoryLedgerLineView(BaseModel):
    id: UUID
    product_definition_id: UUID
    configuration_product_version_id: UUID
    product_price_version_id: UUID | None
    entered_quantity: str
    entered_unit_code: ProductUnitCode
    canonical_signed_quantity: str
    canonical_unit_code: Literal["kg", "L", "each"]
    price_status: Literal["ready", "unavailable"]
    applied_unit_price: str | None
    price_basis_unit_code: ProductUnitCode | None
    currency: str | None
    posted_line_amount: str | None
    frozen_product: dict[str, Any]


class InventoryPostingView(BaseModel):
    id: UUID
    project_id: UUID
    source_configuration_snapshot_id: UUID
    posting_type: Literal["opening_stock", "reversal"]
    status: Literal["posted"]
    posting_date: date
    reversal_of_posting_id: UUID | None
    reversal_posting_id: UUID | None = None
    reason: str | None
    posted_by: UUID
    posted_at: datetime
    lines: list[InventoryLedgerLineView]


class DailyReportCreate(BaseModel):
    report_date: date
    report_number: str = Field(min_length=1, max_length=100)


class DraftPatch(BaseModel):
    expected_version: int = Field(ge=1)
    data: dict[str, Any]


class DecisionRequest(BaseModel):
    expected_checksum: str
    reason: str | None = None


class RevisionView(BaseModel):
    id: UUID
    number: int
    kind: str
    state: str
    version: int
    data: dict[str, Any]
    checksum: str | None
    based_on_revision_id: UUID | None


class ReportView(BaseModel):
    id: UUID
    project_id: UUID
    report_date: str
    report_number: str
    revision: RevisionView


class ReadinessView(BaseModel):
    state: str
    can_submit: bool
    issues: list[dict[str, Any]]


class ExportRequest(BaseModel):
    format: Literal["pdf", "xlsx"]
    visibility: Literal["client", "internal"]


class ExportView(BaseModel):
    id: UUID
    revision_id: UUID
    format: str
    visibility: str
    status: str
    payload_checksum: str
    binary_checksum: str
    template_version: str
    renderer_version: str
