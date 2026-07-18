from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class TenantMixin:
    organisation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)


class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    external_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class OrganisationMembership(Base):
    __tablename__ = "organisation_memberships"
    organisation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class Project(TenantMixin, Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    well_name: Mapped[str] = mapped_column(String(200), nullable=False)
    operator_name: Mapped[str | None] = mapped_column(String(200))
    client_name: Mapped[str | None] = mapped_column(String(200))
    rig_name: Mapped[str | None] = mapped_column(String(200))
    location_text: Mapped[str | None] = mapped_column(String(500))
    time_zone: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_set: Mapped[str] = mapped_column(String(100), nullable=False)
    reporting_start_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    current_configuration_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_versions.id", use_alter=True)
    )
    current_configuration_snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_snapshots.id", use_alter=True)
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("organisation_id", "project_code"),
        CheckConstraint(
            "status IN ('draft', 'active', 'inactive', 'archived')",
            name="ck_projects_status",
        ),
        CheckConstraint("unit_set IN ('Metric', 'Field')", name="ck_projects_unit_set"),
    )


class ProjectMembership(TenantMixin, Base):
    __tablename__ = "project_memberships"
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="report_editor")
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class ConfigurationVersion(TenantMixin, Base):
    __tablename__ = "project_configuration_versions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    activated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("project_id", "version_number"),
        CheckConstraint(
            "state IN ('draft', 'active', 'superseded')",
            name="ck_project_configuration_state",
        ),
        Index(
            "one_active_configuration_per_project",
            "project_id",
            unique=True,
            postgresql_where=state == "active",
        ),
        Index(
            "one_draft_configuration_per_project",
            "project_id",
            unique=True,
            postgresql_where=state == "draft",
        ),
    )


class ProductDefinition(TenantMixin, Base):
    __tablename__ = "project_product_definitions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectProduct(TenantMixin, Base):
    __tablename__ = "project_products"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_versions.id"), nullable=False
    )
    product_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_product_definitions.id"), nullable=False
    )
    item_code: Mapped[str] = mapped_column(String(100), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    alternate_name: Mapped[str | None] = mapped_column(String(200))
    packaging: Mapped[str] = mapped_column(String(30), nullable=False)
    package_size: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    package_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    inventory_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    inventory_unit_code: Mapped[str | None] = mapped_column(String(20))
    specific_gravity: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (
        Index(
            "uq_project_products_configuration_code",
            "configuration_version_id",
            func.lower(item_code),
            unique=True,
        ),
        UniqueConstraint(
            "configuration_version_id",
            "product_definition_id",
            name="uq_project_products_configuration_definition",
        ),
        CheckConstraint("package_size > 0", name="ck_project_products_package_size"),
        CheckConstraint(
            "specific_gravity IS NULL OR specific_gravity > 0",
            name="ck_project_products_specific_gravity",
        ),
        CheckConstraint(
            "(inventory_applicable AND inventory_unit_code IS NOT NULL) OR "
            "(NOT inventory_applicable AND inventory_unit_code IS NULL)",
            name="ck_project_products_inventory_applicability",
        ),
        CheckConstraint(
            "packaging IN ('sack','pail','drum','tote','bulk','case','each','other')",
            name="ck_project_products_packaging",
        ),
        CheckConstraint(
            "package_unit_code IN ('kg','t','lb','L','m3','gal_us','bbl','each')",
            name="ck_project_products_package_unit",
        ),
        CheckConstraint(
            "inventory_unit_code IS NULL OR inventory_unit_code IN "
            "('kg','t','lb','L','m3','gal_us','bbl','each','package')",
            name="ck_project_products_inventory_unit",
        ),
        CheckConstraint(
            "inventory_unit_code IS NULL OR inventory_unit_code = 'package' OR "
            "(inventory_unit_code IN ('kg','t','lb') AND package_unit_code IN ('kg','t','lb')) OR "
            "(inventory_unit_code IN ('L','m3','gal_us','bbl') AND "
            " package_unit_code IN ('L','m3','gal_us','bbl')) OR "
            "(inventory_unit_code = 'each' AND package_unit_code = 'each')",
            name="ck_project_products_unit_dimension",
        ),
    )


class ProductPrice(TenantMixin, Base):
    __tablename__ = "product_price_history"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    project_product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_products.id", ondelete="CASCADE"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_basis_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="ck_product_prices_amount"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_product_prices_range",
        ),
        CheckConstraint(
            "price_basis_unit_code IN ('kg','t','lb','L','m3','gal_us','bbl','each','package')",
            name="ck_product_prices_basis_unit",
        ),
        Index("ix_product_prices_product_start", "project_product_id", "effective_from"),
    )


class InventoryPosting(TenantMixin, Base):
    __tablename__ = "inventory_postings"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    source_configuration_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_snapshots.id"), nullable=False
    )
    posting_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="building")
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    reversal_of_posting_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_postings.id")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    posted_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("reversal_of_posting_id", name="uq_inventory_postings_reversal"),
        CheckConstraint(
            "posting_type IN ('opening_stock','reversal')", name="ck_inventory_postings_type"
        ),
        CheckConstraint("status IN ('building','posted')", name="ck_inventory_postings_status"),
        CheckConstraint(
            "(posting_type = 'opening_stock' AND reversal_of_posting_id IS NULL) OR "
            "(posting_type = 'reversal' AND reversal_of_posting_id IS NOT NULL "
            "AND reason IS NOT NULL)",
            name="ck_inventory_postings_reversal_context",
        ),
        Index("ix_inventory_postings_project_date", "project_id", "posting_date"),
    )


class InventoryLedgerLine(TenantMixin, Base):
    __tablename__ = "inventory_ledger_lines"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    posting_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_postings.id"), nullable=False
    )
    product_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_product_definitions.id"), nullable=False
    )
    configuration_product_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_products.id"), nullable=False
    )
    product_price_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_price_history.id")
    )
    entered_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    entered_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_signed_quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    canonical_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    price_status: Mapped[str] = mapped_column(String(20), nullable=False)
    applied_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    price_basis_unit_code: Mapped[str | None] = mapped_column(String(20))
    price_effective_from: Mapped[date | None] = mapped_column(Date)
    price_effective_to: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    currency_minor_unit_scale: Mapped[int | None] = mapped_column(Integer)
    posted_line_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    frozen_product_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        UniqueConstraint("posting_id", "product_definition_id", name="uq_inventory_line_product"),
        CheckConstraint(
            "price_status IN ('ready','unavailable')", name="ck_inventory_lines_price_status"
        ),
        CheckConstraint(
            "(price_status = 'ready' AND product_price_version_id IS NOT NULL AND "
            "applied_unit_price IS NOT NULL AND price_basis_unit_code IS NOT NULL AND "
            "price_effective_from IS NOT NULL AND currency IS NOT NULL AND "
            "currency_minor_unit_scale IS NOT NULL AND posted_line_amount IS NOT NULL) OR "
            "(price_status = 'unavailable' AND product_price_version_id IS NULL AND "
            "applied_unit_price IS NULL AND price_basis_unit_code IS NULL AND "
            "price_effective_from IS NULL AND price_effective_to IS NULL AND currency IS NULL AND "
            "currency_minor_unit_scale IS NULL AND posted_line_amount IS NULL)",
            name="ck_inventory_lines_price_completeness",
        ),
        CheckConstraint(
            "entered_unit_code IN ('kg','t','lb','L','m3','gal_us','bbl','each','package')",
            name="ck_inventory_lines_entered_unit",
        ),
        CheckConstraint(
            "canonical_unit_code IN ('kg','L','each')", name="ck_inventory_lines_canonical_unit"
        ),
        Index("ix_inventory_ledger_lines_product", "product_definition_id"),
    )


class ConfigurationSnapshot(TenantMixin, Base):
    __tablename__ = "project_configuration_snapshots"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project_configuration_versions.id"),
        unique=True,
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    canonical_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReport(TenantMixin, Base):
    __tablename__ = "daily_reports"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_code: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    report_number: Mapped[str] = mapped_column(String(100), nullable=False)
    active_configuration_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_snapshots.id"), nullable=False
    )
    aggregate_state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("project_id", "report_date", "shift_code"),)


class DailyReportRevision(TenantMixin, Base):
    __tablename__ = "daily_report_revisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    daily_report_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_reports.id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    based_on_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    configuration_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_configuration_snapshots.id"), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("daily_report_id", "revision_number"),
        Index(
            "one_mutable_draft_per_report",
            "daily_report_id",
            unique=True,
            postgresql_where=state.in_(["draft", "ready_for_review"]),
        ),
        Index(
            "one_current_submission_per_report",
            "daily_report_id",
            unique=True,
            postgresql_where=state == "submitted",
        ),
    )


class ReportPayload(TenantMixin, Base):
    __tablename__ = "report_payload_versions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    daily_report_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_report_revisions.id"), unique=True, nullable=False
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[str] = mapped_column(String(30), nullable=False)


class ReportDecision(TenantMixin, Base):
    __tablename__ = "report_decisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    daily_report_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_reports.id"), nullable=False
    )
    daily_report_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_report_revisions.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str | None] = mapped_column(Text)
    expected_payload_checksum: Mapped[str | None] = mapped_column(String(64))
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)


class ReportExport(TenantMixin, Base):
    __tablename__ = "report_exports"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    payload_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_payload_versions.id"), nullable=False
    )
    export_type: Mapped[str] = mapped_column(String(10), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    export_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="original")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    binary_checksum: Mapped[str | None] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(30), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(100), nullable=False)


class AuditEvent(TenantMixin, Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)


class IdempotencyRecord(TenantMixin, Base):
    __tablename__ = "idempotency_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (UniqueConstraint("organisation_id", "operation_type", "idempotency_key"),)
