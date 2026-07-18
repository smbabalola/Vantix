"""Transactional PostgreSQL adapter for the foundation report lifecycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from vantix_core.canonical import payload_checksum
from vantix_core.products import (
    ProductValidationError,
    canonicalise_product,
    select_effective_price,
)
from vantix_core.project_configuration import (
    ConfigurationActivationError,
    build_project_snapshot,
    guard_configuration_activation,
    validate_project_configuration,
)
from vantix_core.readiness import validate_foundation_readiness

from .auth import AuthContext, Capability
from .db import SessionFactory, set_tenant_context
from .models import (
    AuditEvent,
    ConfigurationSnapshot,
    ConfigurationVersion,
    DailyReport,
    DailyReportRevision,
    IdempotencyRecord,
    Organisation,
    OrganisationMembership,
    ProductDefinition,
    ProductPrice,
    Project,
    ProjectMembership,
    ProjectProduct,
    ReportDecision,
    ReportExport,
    ReportPayload,
    User,
)
from .renderers import filter_payload_visibility, render_report
from .schemas import (
    ConfigurationCreate,
    ConfigurationMutationView,
    ConfigurationPatch,
    ConfigurationReadinessView,
    ConfigurationVersionExpectation,
    ConfigurationView,
    DailyReportCreate,
    DecisionRequest,
    DraftPatch,
    ExportRequest,
    ExportView,
    OrganisationCreate,
    OrganisationView,
    ProductPriceCreate,
    ProductPricePatch,
    ProductPriceView,
    ProjectCreate,
    ProjectProductCreate,
    ProjectProductPatch,
    ProjectProductView,
    ProjectView,
    ReadinessView,
    ReportView,
    RevisionView,
)


def _error(status_code: int, code: str, message: str | None = None) -> HTTPException:
    detail: dict[str, str] = {"code": code}
    if message:
        detail["message"] = message
    return HTTPException(status_code, detail=detail)


def _request_hash(value: dict[str, Any]) -> str:
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode()).hexdigest()


class PostgresFoundationRepository:
    """All public mutation methods open and commit exactly one database transaction."""

    @contextmanager
    def _transaction(
        self,
        auth: AuthContext,
        *,
        project_ids: tuple[UUID, ...] = (),
        require_membership: bool = True,
    ) -> Iterator[Session]:
        with SessionFactory.begin() as session:
            set_tenant_context(
                session,
                user_id=auth.user_id,
                organisation_id=auth.organisation_id,
                project_ids=project_ids,
            )
            if require_membership:
                membership = session.get(
                    OrganisationMembership,
                    {"organisation_id": auth.organisation_id, "user_id": auth.user_id},
                )
                if membership is None or membership.status != "active":
                    raise _error(status.HTTP_403_FORBIDDEN, "INACTIVE_MEMBERSHIP")
                if not project_ids:
                    authorised_ids = tuple(
                        session.scalars(
                            select(ProjectMembership.project_id).where(
                                ProjectMembership.user_id == auth.user_id,
                                ProjectMembership.organisation_id == auth.organisation_id,
                            )
                        ).all()
                    )
                    set_tenant_context(
                        session,
                        user_id=auth.user_id,
                        organisation_id=auth.organisation_id,
                        project_ids=authorised_ids,
                    )
            yield session

    def _project(
        self,
        session: Session,
        auth: AuthContext,
        project_id: UUID,
        capability: Capability | None = None,
    ) -> Project:
        project = session.scalar(select(Project).where(Project.id == project_id))
        if project is None or project.organisation_id != auth.organisation_id:
            raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_NOT_FOUND")
        if capability is not None and capability not in self._database_capabilities(
            session, auth, project_id
        ):
            raise _error(status.HTTP_403_FORBIDDEN, "CAPABILITY_DENIED")
        return project

    @staticmethod
    def _database_capabilities(
        session: Session, auth: AuthContext, project_id: UUID
    ) -> frozenset[Capability]:
        """Resolve authority from database memberships, never access-token capability claims."""

        organisation_membership = session.get(
            OrganisationMembership,
            {"organisation_id": auth.organisation_id, "user_id": auth.user_id},
        )
        if organisation_membership and organisation_membership.role in {
            "organisation_admin",
            "operations_manager",
        }:
            return frozenset(Capability)
        membership = session.get(
            ProjectMembership,
            {"project_id": project_id, "user_id": auth.user_id},
        )
        if membership is None:
            return frozenset()
        known = {capability.value: capability for capability in Capability}
        return frozenset(known[value] for value in membership.capabilities if value in known)

    @staticmethod
    def _audit(
        session: Session,
        auth: AuthContext,
        *,
        project_id: UUID | None,
        entity_type: str,
        entity_id: UUID,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str | None = None,
        correlation_id: UUID | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                actor_id=auth.user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                correlation_id=correlation_id or uuid4(),
                before_json=before,
                after_json=after,
                reason=reason,
            )
        )

    @staticmethod
    def _revision_view(revision: DailyReportRevision) -> RevisionView:
        return RevisionView(
            id=revision.id,
            number=revision.revision_number,
            kind=revision.revision_kind,
            state=revision.state,
            version=revision.row_version,
            data=deepcopy(revision.data),
            checksum=None,
            based_on_revision_id=revision.based_on_revision_id,
        )

    def _report_view(self, session: Session, report: DailyReport) -> ReportView:
        revision = session.scalar(
            select(DailyReportRevision)
            .where(DailyReportRevision.daily_report_id == report.id)
            .order_by(DailyReportRevision.revision_number.desc())
            .limit(1)
        )
        if revision is None:
            raise _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "REPORT_REVISION_MISSING")
        view = self._revision_view(revision)
        payload = session.scalar(
            select(ReportPayload).where(ReportPayload.daily_report_revision_id == revision.id)
        )
        if payload:
            view.checksum = payload.payload_checksum
        return ReportView(
            id=report.id,
            project_id=report.project_id,
            report_date=report.report_date.isoformat(),
            report_number=report.report_number,
            revision=view,
        )

    @staticmethod
    def _project_view(project: Project) -> ProjectView:
        return ProjectView(
            id=project.id,
            organisation_id=project.organisation_id,
            project_code=project.project_code,
            project_name=project.project_name,
            well_name=project.well_name,
            operator_name=project.operator_name,
            client_name=project.client_name,
            rig_name=project.rig_name,
            location_text=project.location_text,
            time_zone=project.time_zone,
            currency=project.currency,
            unit_set=cast(Any, project.unit_set),
            reporting_start_date=project.reporting_start_date,
            status=project.status,
            row_version=project.row_version,
            current_configuration_version_id=project.current_configuration_version_id,
            active_configuration_snapshot_id=project.current_configuration_snapshot_id,
        )

    @staticmethod
    def _project_configuration_data(project: Project) -> dict[str, Any]:
        return {
            "project_code": project.project_code,
            "project_name": project.project_name,
            "well_name": project.well_name,
            "operator_name": project.operator_name,
            "client_name": project.client_name,
            "rig_name": project.rig_name,
            "location_text": project.location_text,
            "time_zone": project.time_zone,
            "currency": project.currency,
            "unit_set": project.unit_set,
        }

    @staticmethod
    def _configuration_view(
        session: Session, configuration: ConfigurationVersion
    ) -> ConfigurationView:
        snapshot = session.scalar(
            select(ConfigurationSnapshot).where(
                ConfigurationSnapshot.configuration_version_id == configuration.id
            )
        )
        return ConfigurationView(
            id=configuration.id,
            project_id=configuration.project_id,
            version=configuration.version_number,
            state=cast(Any, configuration.state),
            row_version=configuration.row_version,
            data=deepcopy(configuration.data),
            change_summary=configuration.change_summary,
            activated_by=configuration.activated_by,
            activated_at=configuration.activated_at,
            snapshot_id=snapshot.id if snapshot else None,
            checksum=snapshot.canonical_checksum if snapshot else None,
        )

    @staticmethod
    def _decimal_string(value: Decimal) -> str:
        return "0" if value == 0 else format(value.normalize(), "f")

    @classmethod
    def _price_view(cls, price: ProductPrice) -> ProductPriceView:
        return ProductPriceView(
            id=price.id,
            project_product_id=price.project_product_id,
            effective_from=price.effective_from,
            effective_to=price.effective_to,
            unit_price=cls._decimal_string(price.unit_price),
            currency=price.currency,
            price_basis_unit_code=cast(Any, price.price_basis_unit_code),
            source=price.source,
        )

    @classmethod
    def _product_view(
        cls, session: Session, product: ProjectProduct, configuration_row_version: int
    ) -> ProjectProductView:
        prices = session.scalars(
            select(ProductPrice)
            .where(ProductPrice.project_product_id == product.id)
            .order_by(ProductPrice.effective_from, ProductPrice.id)
        ).all()
        return ProjectProductView(
            id=product.id,
            product_definition_id=product.product_definition_id,
            project_id=product.project_id,
            configuration_version_id=product.configuration_version_id,
            configuration_row_version=configuration_row_version,
            item_code=product.item_code,
            item_name=product.item_name,
            alternate_name=product.alternate_name,
            packaging=cast(Any, product.packaging),
            package_size=cls._decimal_string(product.package_size),
            package_unit_code=cast(Any, product.package_unit_code),
            inventory_applicable=product.inventory_applicable,
            inventory_unit_code=cast(Any, product.inventory_unit_code),
            specific_gravity=(
                cls._decimal_string(product.specific_gravity)
                if product.specific_gravity is not None
                else None
            ),
            active=product.active,
            prices=[cls._price_view(price) for price in prices],
        )

    @classmethod
    def _configuration_payload(
        cls, session: Session, configuration: ConfigurationVersion
    ) -> dict[str, Any]:
        products = session.scalars(
            select(ProjectProduct)
            .where(ProjectProduct.configuration_version_id == configuration.id)
            .order_by(ProjectProduct.item_code, ProjectProduct.id)
        ).all()
        payload = deepcopy(configuration.data)
        payload["products"] = [
            cls._product_view(session, product, configuration.row_version).model_dump(
                mode="json",
                exclude={"project_id", "configuration_version_id", "configuration_row_version"},
                exclude_none=True,
            )
            for product in products
        ]
        return payload

    @staticmethod
    def _product_error(exc: ProductValidationError) -> HTTPException:
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc), "field": exc.field},
        )

    @staticmethod
    def _lock_idempotency(
        session: Session,
        auth: AuthContext,
        operation_type: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyRecord | None:
        lock_key = f"{auth.organisation_id}:{operation_type}:{key}"
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})
        existing = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organisation_id == auth.organisation_id,
                IdempotencyRecord.operation_type == operation_type,
                IdempotencyRecord.idempotency_key == key,
            )
        )
        if existing and existing.request_hash != request_hash:
            raise _error(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "Key reused with a different request.",
            )
        return existing

    @staticmethod
    def _remember_idempotency(
        session: Session,
        auth: AuthContext,
        operation_type: str,
        key: str,
        request_hash: str,
        resource_type: str,
        resource_id: UUID,
        response: Any,
        response_status: int = 200,
    ) -> None:
        if hasattr(response, "model_dump"):
            response_json = response.model_dump(mode="json")
        else:
            response_json = cast(dict[str, Any], response)
        session.add(
            IdempotencyRecord(
                organisation_id=auth.organisation_id,
                operation_type=operation_type,
                idempotency_key=key,
                request_hash=request_hash,
                resource_type=resource_type,
                resource_id=resource_id,
                response_status=response_status,
                response_json=response_json,
            )
        )

    def create_organisation(self, auth: AuthContext, body: OrganisationCreate) -> OrganisationView:
        with self._transaction(auth, require_membership=False) as session:
            if session.get(Organisation, auth.organisation_id):
                raise _error(status.HTTP_409_CONFLICT, "ORGANISATION_EXISTS")
            user = session.get(User, auth.user_id)
            if user is None:
                session.add(
                    User(
                        id=auth.user_id,
                        external_subject=f"mapped:{auth.user_id}",
                        status="active",
                    )
                )
                session.flush()
            # Use an explicit INSERT without RETURNING while the organisation has no
            # membership row. PostgreSQL applies SELECT RLS to INSERT ... RETURNING,
            # which would otherwise create a bootstrap cycle with the membership FK.
            session.execute(
                text("INSERT INTO organisations (id, name) VALUES (:id, :name)"),
                {"id": auth.organisation_id, "name": body.name},
            )
            session.add(
                OrganisationMembership(
                    organisation_id=auth.organisation_id,
                    user_id=auth.user_id,
                    role="organisation_admin",
                    status="active",
                )
            )
            session.flush()
            self._audit(
                session,
                auth,
                project_id=None,
                entity_type="organisation",
                entity_id=auth.organisation_id,
                action="create",
                before=None,
                after={"name": body.name},
            )
            return OrganisationView(id=auth.organisation_id, name=body.name)

    def create_project(
        self, auth: AuthContext, body: ProjectCreate, organisation_id: UUID
    ) -> ProjectView:
        if organisation_id != auth.organisation_id:
            raise _error(status.HTTP_404_NOT_FOUND, "ORGANISATION_NOT_FOUND")
        project_id = uuid4()
        with self._transaction(auth, project_ids=(project_id,)) as session:
            organisation_membership = session.get(
                OrganisationMembership,
                {"organisation_id": auth.organisation_id, "user_id": auth.user_id},
            )
            if organisation_membership is None or organisation_membership.role not in {
                "organisation_admin",
                "operations_manager",
            }:
                raise _error(status.HTTP_403_FORBIDDEN, "CAPABILITY_DENIED")
            project = Project(
                id=project_id,
                organisation_id=auth.organisation_id,
                **body.model_dump(),
            )
            session.add(project)
            session.add(
                ProjectMembership(
                    organisation_id=auth.organisation_id,
                    project_id=project_id,
                    user_id=auth.user_id,
                    role="project_admin",
                    capabilities=[capability.value for capability in Capability],
                )
            )
            session.flush()
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="project",
                entity_id=project_id,
                action="create",
                before=None,
                after=body.model_dump(mode="json"),
            )
            return self._project_view(project)

    def list_projects(self, auth: AuthContext) -> list[ProjectView]:
        with self._transaction(auth) as session:
            projects = session.scalars(select(Project).order_by(Project.project_code)).all()
            return [self._project_view(project) for project in projects]

    def get_project(self, auth: AuthContext, project_id: UUID) -> ProjectView:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            return self._project_view(self._project(session, auth, project_id))

    def create_configuration(
        self,
        auth: AuthContext,
        project_id: UUID,
        body: ConfigurationCreate,
        idempotency_key: str,
    ) -> ConfigurationView:
        request = {"project_id": str(project_id), **body.model_dump(mode="json")}
        request_hash = _request_hash(request)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            project = session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            if project is None or project.organisation_id != auth.organisation_id:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_NOT_FOUND")
            if Capability.CONFIGURE_PROJECT not in self._database_capabilities(
                session, auth, project_id
            ):
                raise _error(status.HTTP_403_FORBIDDEN, "CAPABILITY_DENIED")
            existing = self._lock_idempotency(
                session, auth, "create_configuration", idempotency_key, request_hash
            )
            if existing:
                return ConfigurationView.model_validate(existing.response_json)
            latest = session.scalar(
                select(ConfigurationVersion)
                .where(ConfigurationVersion.project_id == project_id)
                .order_by(ConfigurationVersion.version_number.desc())
                .limit(1)
            )
            if latest is not None and latest.state == "draft":
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "CONFIGURATION_DRAFT_EXISTS",
                    "Update the existing draft before creating another revision.",
                )
            active = None
            if project.current_configuration_version_id:
                active = session.get(ConfigurationVersion, project.current_configuration_version_id)
            if body.data is not None:
                data = body.data.model_dump(mode="json", exclude_none=True)
            elif body.copy_active and active is not None:
                data = deepcopy(active.data)
            else:
                data = {"default_interval_id": None, "intervals": []}
            configuration = ConfigurationVersion(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                version_number=(latest.version_number if latest else 0) + 1,
                state="draft",
                data=data,
                change_summary=body.change_summary,
                created_by=auth.user_id,
            )
            session.add(configuration)
            session.flush()
            if body.data is None and body.copy_active and active is not None:
                active_products = session.scalars(
                    select(ProjectProduct).where(
                        ProjectProduct.configuration_version_id == active.id
                    )
                ).all()
                for source_product in active_products:
                    copied_product = ProjectProduct(
                        id=uuid4(),
                        organisation_id=auth.organisation_id,
                        project_id=project_id,
                        configuration_version_id=configuration.id,
                        product_definition_id=source_product.product_definition_id,
                        item_code=source_product.item_code,
                        item_name=source_product.item_name,
                        alternate_name=source_product.alternate_name,
                        packaging=source_product.packaging,
                        package_size=source_product.package_size,
                        package_unit_code=source_product.package_unit_code,
                        inventory_applicable=source_product.inventory_applicable,
                        inventory_unit_code=source_product.inventory_unit_code,
                        specific_gravity=source_product.specific_gravity,
                        active=source_product.active,
                    )
                    session.add(copied_product)
                    session.flush()
                    source_prices = session.scalars(
                        select(ProductPrice).where(
                            ProductPrice.project_product_id == source_product.id
                        )
                    ).all()
                    for source_price in source_prices:
                        session.add(
                            ProductPrice(
                                id=uuid4(),
                                organisation_id=auth.organisation_id,
                                project_id=project_id,
                                project_product_id=copied_product.id,
                                effective_from=source_price.effective_from,
                                effective_to=source_price.effective_to,
                                unit_price=source_price.unit_price,
                                currency=source_price.currency,
                                price_basis_unit_code=source_price.price_basis_unit_code,
                                source=source_price.source,
                            )
                        )
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="project_configuration_version",
                entity_id=configuration.id,
                action="create",
                before=None,
                after={"version": configuration.version_number, "state": "draft"},
            )
            view = self._configuration_view(session, configuration)
            self._remember_idempotency(
                session,
                auth,
                "create_configuration",
                idempotency_key,
                request_hash,
                "project_configuration_version",
                configuration.id,
                view,
                response_status=201,
            )
            return view

    def list_configurations(self, auth: AuthContext, project_id: UUID) -> list[ConfigurationView]:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            self._project(session, auth, project_id, Capability.CONFIGURE_PROJECT)
            configurations = session.scalars(
                select(ConfigurationVersion)
                .where(ConfigurationVersion.project_id == project_id)
                .order_by(ConfigurationVersion.version_number.desc())
            ).all()
            return [self._configuration_view(session, item) for item in configurations]

    def get_configuration(
        self, auth: AuthContext, project_id: UUID, version_id: UUID
    ) -> ConfigurationView:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            self._project(session, auth, project_id, Capability.CONFIGURE_PROJECT)
            configuration = session.scalar(
                select(ConfigurationVersion).where(
                    ConfigurationVersion.id == version_id,
                    ConfigurationVersion.project_id == project_id,
                )
            )
            if configuration is None:
                raise _error(status.HTTP_404_NOT_FOUND, "CONFIGURATION_NOT_FOUND")
            return self._configuration_view(session, configuration)

    def patch_configuration(
        self,
        auth: AuthContext,
        project_id: UUID,
        version_id: UUID,
        body: ConfigurationPatch,
    ) -> ConfigurationView:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            self._project(session, auth, project_id, Capability.CONFIGURE_PROJECT)
            configuration = session.scalar(
                select(ConfigurationVersion)
                .where(
                    ConfigurationVersion.id == version_id,
                    ConfigurationVersion.project_id == project_id,
                )
                .with_for_update()
            )
            if configuration is None:
                raise _error(status.HTTP_404_NOT_FOUND, "CONFIGURATION_NOT_FOUND")
            if configuration.state != "draft":
                raise _error(status.HTTP_423_LOCKED, "CONFIGURATION_LOCKED")
            if configuration.row_version != body.expected_version:
                raise _error(status.HTTP_412_PRECONDITION_FAILED, "CONFIGURATION_VERSION_CONFLICT")
            before = {
                "data": deepcopy(configuration.data),
                "row_version": configuration.row_version,
            }
            configuration.data = body.data.model_dump(mode="json", exclude_none=True)
            configuration.change_summary = body.change_summary
            configuration.row_version += 1
            session.flush()
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="project_configuration_version",
                entity_id=configuration.id,
                action="update_draft",
                before=before,
                after={
                    "data": deepcopy(configuration.data),
                    "row_version": configuration.row_version,
                },
            )
            return self._configuration_view(session, configuration)

    def _lock_product_configuration(
        self,
        session: Session,
        auth: AuthContext,
        project_id: UUID,
        configuration_version_id: UUID,
        expected_version: int,
    ) -> tuple[Project, ConfigurationVersion]:
        project = self._project(session, auth, project_id, Capability.CONFIGURE_PROJECT)
        configuration = session.scalar(
            select(ConfigurationVersion)
            .where(
                ConfigurationVersion.id == configuration_version_id,
                ConfigurationVersion.project_id == project_id,
            )
            .with_for_update()
        )
        if configuration is None:
            raise _error(status.HTTP_404_NOT_FOUND, "CONFIGURATION_NOT_FOUND")
        if configuration.state != "draft":
            raise _error(status.HTTP_423_LOCKED, "CONFIGURATION_LOCKED")
        if configuration.row_version != expected_version:
            raise _error(status.HTTP_412_PRECONDITION_FAILED, "CONFIGURATION_VERSION_CONFLICT")
        return project, configuration

    def list_products(
        self, auth: AuthContext, project_id: UUID, configuration_version_id: UUID
    ) -> list[ProjectProductView]:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            self._project(session, auth, project_id, Capability.CONFIGURE_PROJECT)
            configuration = session.scalar(
                select(ConfigurationVersion).where(
                    ConfigurationVersion.id == configuration_version_id,
                    ConfigurationVersion.project_id == project_id,
                )
            )
            if configuration is None:
                raise _error(status.HTTP_404_NOT_FOUND, "CONFIGURATION_NOT_FOUND")
            products = session.scalars(
                select(ProjectProduct)
                .where(ProjectProduct.configuration_version_id == configuration.id)
                .order_by(ProjectProduct.item_code, ProjectProduct.id)
            ).all()
            return [
                self._product_view(session, product, configuration.row_version)
                for product in products
            ]

    def create_product(
        self, auth: AuthContext, project_id: UUID, body: ProjectProductCreate
    ) -> ProjectProductView:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            project, configuration = self._lock_product_configuration(
                session,
                auth,
                project_id,
                body.configuration_version_id,
                body.expected_configuration_version,
            )
            product_id = uuid4()
            product_definition_id = uuid4()
            values = body.model_dump(
                mode="json",
                exclude={"configuration_version_id", "expected_configuration_version"},
                exclude_none=True,
            )
            try:
                canonical = canonicalise_product(
                    {
                        "id": str(product_id),
                        "product_definition_id": str(product_definition_id),
                        **values,
                        "prices": [],
                    },
                    project.currency,
                    require_price=False,
                )
            except ProductValidationError as exc:
                raise self._product_error(exc) from exc
            duplicate = session.scalar(
                select(ProjectProduct.id).where(
                    ProjectProduct.configuration_version_id == configuration.id,
                    func.lower(ProjectProduct.item_code) == canonical["item_code"].lower(),
                )
            )
            if duplicate is not None:
                raise _error(status.HTTP_409_CONFLICT, "PRODUCT_CODE_EXISTS")
            session.add(
                ProductDefinition(
                    id=product_definition_id,
                    organisation_id=auth.organisation_id,
                    project_id=project_id,
                )
            )
            product = ProjectProduct(
                id=product_id,
                organisation_id=auth.organisation_id,
                project_id=project_id,
                configuration_version_id=configuration.id,
                product_definition_id=product_definition_id,
                item_code=canonical["item_code"],
                item_name=canonical["item_name"],
                alternate_name=canonical.get("alternate_name"),
                packaging=canonical["packaging"],
                package_size=Decimal(canonical["package_size"]),
                package_unit_code=canonical["package_unit_code"],
                inventory_applicable=canonical["inventory_applicable"],
                inventory_unit_code=canonical.get("inventory_unit_code"),
                specific_gravity=(
                    Decimal(canonical["specific_gravity"])
                    if canonical.get("specific_gravity") is not None
                    else None
                ),
                active=canonical.get("active", True),
            )
            session.add(product)
            configuration.row_version += 1
            session.flush()
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="project_product",
                entity_id=product.id,
                action="create",
                before=None,
                after=canonical,
            )
            return self._product_view(session, product, configuration.row_version)

    def patch_product(
        self, auth: AuthContext, product_id: UUID, body: ProjectProductPatch
    ) -> ProjectProductView:
        with self._transaction(auth, require_membership=True) as session:
            product = session.scalar(select(ProjectProduct).where(ProjectProduct.id == product_id))
            if product is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_PRODUCT_NOT_FOUND")
            project, configuration = self._lock_product_configuration(
                session,
                auth,
                product.project_id,
                product.configuration_version_id,
                body.expected_configuration_version,
            )
            before = self._product_view(session, product, configuration.row_version).model_dump(
                mode="json"
            )
            values = body.model_dump(
                mode="json", exclude={"expected_configuration_version"}, exclude_none=True
            )
            try:
                canonical = canonicalise_product(
                    {
                        "id": str(product.id),
                        "product_definition_id": str(product.product_definition_id),
                        **values,
                        "prices": before["prices"],
                    },
                    project.currency,
                    require_price=False,
                )
            except ProductValidationError as exc:
                raise self._product_error(exc) from exc
            duplicate = session.scalar(
                select(ProjectProduct.id).where(
                    ProjectProduct.configuration_version_id == configuration.id,
                    ProjectProduct.id != product.id,
                    func.lower(ProjectProduct.item_code) == canonical["item_code"].lower(),
                )
            )
            if duplicate is not None:
                raise _error(status.HTTP_409_CONFLICT, "PRODUCT_CODE_EXISTS")
            for field in (
                "item_code",
                "item_name",
                "alternate_name",
                "packaging",
                "package_unit_code",
                "inventory_applicable",
                "inventory_unit_code",
                "active",
            ):
                setattr(product, field, canonical.get(field))
            product.package_size = Decimal(canonical["package_size"])
            product.specific_gravity = (
                Decimal(canonical["specific_gravity"])
                if canonical.get("specific_gravity") is not None
                else None
            )
            configuration.row_version += 1
            session.flush()
            after = self._product_view(session, product, configuration.row_version)
            self._audit(
                session,
                auth,
                project_id=product.project_id,
                entity_type="project_product",
                entity_id=product.id,
                action="update",
                before=before,
                after=after.model_dump(mode="json"),
            )
            return after

    def delete_product(
        self, auth: AuthContext, product_id: UUID, body: ConfigurationVersionExpectation
    ) -> ConfigurationMutationView:
        with self._transaction(auth, require_membership=True) as session:
            product = session.scalar(select(ProjectProduct).where(ProjectProduct.id == product_id))
            if product is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_PRODUCT_NOT_FOUND")
            _, configuration = self._lock_product_configuration(
                session,
                auth,
                product.project_id,
                product.configuration_version_id,
                body.expected_configuration_version,
            )
            before = self._product_view(session, product, configuration.row_version).model_dump(
                mode="json"
            )
            session.execute(
                delete(ProductPrice).where(ProductPrice.project_product_id == product.id)
            )
            session.flush()
            session.delete(product)
            configuration.row_version += 1
            session.flush()
            self._audit(
                session,
                auth,
                project_id=product.project_id,
                entity_type="project_product",
                entity_id=product.id,
                action="delete_draft",
                before=before,
                after=None,
            )
            return ConfigurationMutationView(configuration_row_version=configuration.row_version)

    def create_product_price(
        self, auth: AuthContext, product_id: UUID, body: ProductPriceCreate
    ) -> ProjectProductView:
        with self._transaction(auth, require_membership=True) as session:
            product = session.scalar(select(ProjectProduct).where(ProjectProduct.id == product_id))
            if product is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_PRODUCT_NOT_FOUND")
            project, configuration = self._lock_product_configuration(
                session,
                auth,
                product.project_id,
                product.configuration_version_id,
                body.expected_configuration_version,
            )
            product_view = self._product_view(session, product, configuration.row_version)
            price_id = uuid4()
            candidate_price = {
                "id": str(price_id),
                **body.model_dump(
                    mode="json", exclude={"expected_configuration_version"}, exclude_none=True
                ),
            }
            candidate = product_view.model_dump(
                mode="json",
                exclude={"project_id", "configuration_version_id", "configuration_row_version"},
                exclude_none=True,
            )
            candidate["prices"] = [*candidate["prices"], candidate_price]
            try:
                canonical = canonicalise_product(candidate, project.currency, require_price=False)
            except ProductValidationError as exc:
                raise self._product_error(exc) from exc
            canonical_price = next(
                item for item in canonical["prices"] if item["id"] == str(price_id)
            )
            price = ProductPrice(
                id=price_id,
                organisation_id=auth.organisation_id,
                project_id=product.project_id,
                project_product_id=product.id,
                effective_from=date.fromisoformat(canonical_price["effective_from"]),
                effective_to=(
                    date.fromisoformat(canonical_price["effective_to"])
                    if canonical_price.get("effective_to") is not None
                    else None
                ),
                unit_price=Decimal(canonical_price["unit_price"]),
                currency=canonical_price["currency"],
                price_basis_unit_code=canonical_price["price_basis_unit_code"],
                source=canonical_price.get("source"),
            )
            session.add(price)
            configuration.row_version += 1
            session.flush()
            self._audit(
                session,
                auth,
                project_id=product.project_id,
                entity_type="product_price",
                entity_id=price.id,
                action="create",
                before=None,
                after=canonical_price,
            )
            return self._product_view(session, product, configuration.row_version)

    def patch_product_price(
        self, auth: AuthContext, price_id: UUID, body: ProductPricePatch
    ) -> ProjectProductView:
        with self._transaction(auth, require_membership=True) as session:
            price = session.scalar(select(ProductPrice).where(ProductPrice.id == price_id))
            if price is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PRODUCT_PRICE_NOT_FOUND")
            product = session.scalar(
                select(ProjectProduct).where(ProjectProduct.id == price.project_product_id)
            )
            if product is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_PRODUCT_NOT_FOUND")
            project, configuration = self._lock_product_configuration(
                session,
                auth,
                product.project_id,
                product.configuration_version_id,
                body.expected_configuration_version,
            )
            product_view = self._product_view(session, product, configuration.row_version)
            before = self._price_view(price).model_dump(mode="json")
            replacement = {
                "id": str(price.id),
                **body.model_dump(
                    mode="json", exclude={"expected_configuration_version"}, exclude_none=True
                ),
            }
            candidate = product_view.model_dump(
                mode="json",
                exclude={"project_id", "configuration_version_id", "configuration_row_version"},
                exclude_none=True,
            )
            candidate["prices"] = [
                replacement if item["id"] == str(price.id) else item for item in candidate["prices"]
            ]
            try:
                canonical = canonicalise_product(candidate, project.currency, require_price=False)
            except ProductValidationError as exc:
                raise self._product_error(exc) from exc
            canonical_price = next(
                item for item in canonical["prices"] if item["id"] == str(price.id)
            )
            price.effective_from = date.fromisoformat(canonical_price["effective_from"])
            price.effective_to = (
                date.fromisoformat(canonical_price["effective_to"])
                if canonical_price.get("effective_to") is not None
                else None
            )
            price.unit_price = Decimal(canonical_price["unit_price"])
            price.currency = canonical_price["currency"]
            price.price_basis_unit_code = canonical_price["price_basis_unit_code"]
            price.source = canonical_price.get("source")
            configuration.row_version += 1
            session.flush()
            self._audit(
                session,
                auth,
                project_id=product.project_id,
                entity_type="product_price",
                entity_id=price.id,
                action="update",
                before=before,
                after=canonical_price,
            )
            return self._product_view(session, product, configuration.row_version)

    def delete_product_price(
        self, auth: AuthContext, price_id: UUID, body: ConfigurationVersionExpectation
    ) -> ProjectProductView:
        with self._transaction(auth, require_membership=True) as session:
            price = session.scalar(select(ProductPrice).where(ProductPrice.id == price_id))
            if price is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PRODUCT_PRICE_NOT_FOUND")
            product = session.scalar(
                select(ProjectProduct).where(ProjectProduct.id == price.project_product_id)
            )
            if product is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_PRODUCT_NOT_FOUND")
            _, configuration = self._lock_product_configuration(
                session,
                auth,
                product.project_id,
                product.configuration_version_id,
                body.expected_configuration_version,
            )
            before = self._price_view(price).model_dump(mode="json")
            session.delete(price)
            configuration.row_version += 1
            session.flush()
            self._audit(
                session,
                auth,
                project_id=product.project_id,
                entity_type="product_price",
                entity_id=price.id,
                action="delete_draft",
                before=before,
                after=None,
            )
            return self._product_view(session, product, configuration.row_version)

    def price_at(
        self, auth: AuthContext, product_id: UUID, effective_date: date
    ) -> ProductPriceView:
        with self._transaction(auth, require_membership=True) as session:
            product = session.scalar(select(ProjectProduct).where(ProjectProduct.id == product_id))
            if product is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_PRODUCT_NOT_FOUND")
            self._project(session, auth, product.project_id, Capability.CONFIGURE_PROJECT)
            prices = session.scalars(
                select(ProductPrice)
                .where(ProductPrice.project_product_id == product.id)
                .order_by(ProductPrice.effective_from)
            ).all()
            selected = select_effective_price(
                [self._price_view(price).model_dump(mode="json") for price in prices],
                effective_date,
            )
            if selected is None:
                raise _error(status.HTTP_404_NOT_FOUND, "PRICE_NOT_EFFECTIVE")
            return ProductPriceView.model_validate(selected)

    def validate_configuration(
        self, auth: AuthContext, project_id: UUID, version_id: UUID
    ) -> ConfigurationReadinessView:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            project = self._project(session, auth, project_id, Capability.CONFIGURE_PROJECT)
            configuration = session.scalar(
                select(ConfigurationVersion).where(
                    ConfigurationVersion.id == version_id,
                    ConfigurationVersion.project_id == project_id,
                )
            )
            if configuration is None:
                raise _error(status.HTTP_404_NOT_FOUND, "CONFIGURATION_NOT_FOUND")
            payload = self._configuration_payload(session, configuration)
            readiness = validate_project_configuration(
                self._project_configuration_data(project), payload
            )
            return ConfigurationReadinessView(
                state=readiness.state,
                can_activate=readiness.can_activate,
                validated_version=configuration.row_version,
                draft_checksum=payload_checksum(payload),
                issues=[asdict(issue) for issue in readiness.issues],
            )

    def activate_configuration(
        self,
        auth: AuthContext,
        project_id: UUID,
        version_id: UUID,
        idempotency_key: str,
        expected_version: int,
        expected_checksum: str,
    ) -> ConfigurationView:
        request = {
            "project_id": str(project_id),
            "version_id": str(version_id),
            "expected_version": expected_version,
            "expected_checksum": expected_checksum,
        }
        request_hash = _request_hash(request)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            project = session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            if project is None or project.organisation_id != auth.organisation_id:
                raise _error(status.HTTP_404_NOT_FOUND, "PROJECT_NOT_FOUND")
            if Capability.CONFIGURE_PROJECT not in self._database_capabilities(
                session, auth, project_id
            ):
                raise _error(status.HTTP_403_FORBIDDEN, "CAPABILITY_DENIED")
            existing = self._lock_idempotency(
                session, auth, "activate_configuration", idempotency_key, request_hash
            )
            if existing:
                return ConfigurationView.model_validate(existing.response_json)
            configuration = session.scalar(
                select(ConfigurationVersion)
                .where(
                    ConfigurationVersion.id == version_id,
                    ConfigurationVersion.project_id == project_id,
                )
                .with_for_update()
            )
            if configuration is None:
                raise _error(status.HTTP_404_NOT_FOUND, "CONFIGURATION_NOT_FOUND")
            latest = session.scalar(
                select(ConfigurationVersion)
                .where(ConfigurationVersion.project_id == project_id)
                .order_by(ConfigurationVersion.version_number.desc())
                .limit(1)
            )
            current = (
                session.get(ConfigurationVersion, project.current_configuration_version_id)
                if project.current_configuration_version_id
                else None
            )
            payload = self._configuration_payload(session, configuration)
            try:
                guard_configuration_activation(
                    project=self._project_configuration_data(project),
                    data=payload,
                    state=configuration.state,
                    row_version=configuration.row_version,
                    expected_version=expected_version,
                    expected_checksum=expected_checksum,
                    version_number=configuration.version_number,
                    latest_version_number=(
                        latest.version_number
                        if latest is not None
                        else configuration.version_number
                    ),
                    active_version_number=(current.version_number if current is not None else None),
                )
            except ConfigurationActivationError as exc:
                status_codes = {
                    "CONFIGURATION_VERSION_CONFLICT": status.HTTP_412_PRECONDITION_FAILED,
                    "CONFIGURATION_NOT_READY": status.HTTP_422_UNPROCESSABLE_ENTITY,
                }
                raise _error(
                    status_codes.get(exc.code, status.HTTP_409_CONFLICT),
                    exc.code,
                    str(exc),
                ) from exc
            activated_at = datetime.now(UTC)
            snapshot_id = uuid4()
            snapshot_json, checksum = build_project_snapshot(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                project=self._project_configuration_data(project),
                data=payload,
                version_id=configuration.id,
                version_number=configuration.version_number,
                activated_by=auth.user_id,
                activated_at=activated_at,
            )
            snapshot = ConfigurationSnapshot(
                id=snapshot_id,
                organisation_id=auth.organisation_id,
                project_id=project_id,
                configuration_version_id=configuration.id,
                schema_version="1.2",
                snapshot_json=snapshot_json,
                canonical_checksum=checksum,
            )
            session.add(snapshot)
            if project.current_configuration_version_id:
                previous = session.get(
                    ConfigurationVersion, project.current_configuration_version_id
                )
                if previous is not None and previous.id != configuration.id:
                    previous.state = "superseded"
                    session.flush()
            configuration.state = "active"
            configuration.activated_by = auth.user_id
            configuration.activated_at = activated_at
            project.status = "active"
            project.current_configuration_version_id = configuration.id
            project.current_configuration_snapshot_id = snapshot.id
            project.row_version += 1
            session.flush()
            view = self._configuration_view(session, configuration)
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="project_configuration_snapshot",
                entity_id=snapshot.id,
                action="activate",
                before=None,
                after={"checksum": snapshot.canonical_checksum},
            )
            self._remember_idempotency(
                session,
                auth,
                "activate_configuration",
                idempotency_key,
                request_hash,
                "project_configuration_snapshot",
                snapshot.id,
                view,
            )
            return view

    def create_daily_report(
        self,
        auth: AuthContext,
        project_id: UUID,
        body: DailyReportCreate,
        idempotency_key: str,
    ) -> ReportView:
        request = {"project_id": str(project_id), **body.model_dump(mode="json")}
        request_hash = _request_hash(request)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            existing = self._lock_idempotency(
                session, auth, "create_daily_report", idempotency_key, request_hash
            )
            if existing:
                return ReportView.model_validate(existing.response_json)
            project = self._project(session, auth, project_id, Capability.EDIT_REPORT)
            if project.current_configuration_snapshot_id is None:
                raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "ACTIVE_CONFIGURATION_REQUIRED")
            report = DailyReport(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                report_date=body.report_date,
                report_number=body.report_number,
                active_configuration_snapshot_id=project.current_configuration_snapshot_id,
                aggregate_state="draft",
            )
            session.add(report)
            session.flush()
            revision = DailyReportRevision(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                daily_report_id=report.id,
                revision_number=1,
                revision_kind="original",
                state="draft",
                configuration_snapshot_id=project.current_configuration_snapshot_id,
                data={},
            )
            session.add(revision)
            session.flush()
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="daily_report_revision",
                entity_id=revision.id,
                action="create_draft",
                before=None,
                after={"state": "draft", "version": 1},
            )
            view = self._report_view(session, report)
            self._remember_idempotency(
                session,
                auth,
                "create_daily_report",
                idempotency_key,
                request_hash,
                "daily_report",
                report.id,
                view,
                201,
            )
            return view

    def get_report(self, auth: AuthContext, report_id: UUID) -> ReportView:
        with self._transaction(auth) as bootstrap:
            project_id = bootstrap.scalar(
                select(DailyReport.project_id).where(DailyReport.id == report_id)
            )
        if project_id is None:
            raise _error(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
        with self._transaction(auth, project_ids=(project_id,)) as session:
            report = session.scalar(select(DailyReport).where(DailyReport.id == report_id))
            if report is None:
                raise _error(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
            self._project(session, auth, project_id)
            view = self._report_view(session, report)
            capabilities = self._database_capabilities(session, auth, project_id)
            if view.revision.state != "approved":
                if Capability.VIEW_DRAFT_REPORT not in capabilities:
                    raise _error(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
            elif not capabilities.intersection(
                {Capability.VIEW_CLIENT_REPORT, Capability.VIEW_DRAFT_REPORT}
            ):
                raise _error(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
            if Capability.VIEW_INTERNAL_CONTENT not in capabilities:
                filtered = filter_payload_visibility({"operations": view.revision.data}, "client")
                view.revision.data = filtered.get("operations", {})
            return view

    def _revision_and_report(
        self,
        session: Session,
        auth: AuthContext,
        revision_id: UUID,
        capability: Capability | None,
        *,
        lock: bool = False,
    ) -> tuple[DailyReportRevision, DailyReport]:
        statement = select(DailyReportRevision).where(DailyReportRevision.id == revision_id)
        if lock:
            statement = statement.with_for_update()
        revision = session.scalar(statement)
        if revision is None:
            raise _error(status.HTTP_404_NOT_FOUND, "REVISION_NOT_FOUND")
        report = session.get(DailyReport, revision.daily_report_id)
        if report is None:
            raise _error(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
        self._project(session, auth, report.project_id, capability)
        return revision, report

    def patch_section(
        self,
        auth: AuthContext,
        revision_id: UUID,
        section_key: str,
        body: DraftPatch,
    ) -> ReportView:
        project_id = self._project_id_for_revision(auth, revision_id)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            revision, report = self._revision_and_report(
                session, auth, revision_id, Capability.EDIT_REPORT, lock=True
            )
            if revision.state not in {"draft", "ready_for_review"}:
                raise _error(status.HTTP_423_LOCKED, "REPORT_REVISION_LOCKED")
            if revision.row_version != body.expected_version:
                raise _error(status.HTTP_412_PRECONDITION_FAILED, "REPORT_VERSION_CONFLICT")
            before = {"version": revision.row_version, "data": deepcopy(revision.data)}
            data = deepcopy(revision.data)
            data[section_key] = deepcopy(body.data)
            revision.data = data
            revision.row_version += 1
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="daily_report_revision",
                entity_id=revision.id,
                action="update_draft",
                before=before,
                after={"version": revision.row_version, "data": data},
            )
            return self._report_view(session, report)

    def _project_id_for_revision(self, auth: AuthContext, revision_id: UUID) -> UUID:
        with self._transaction(auth) as session:
            project_id = session.scalar(
                select(DailyReportRevision.project_id).where(DailyReportRevision.id == revision_id)
            )
        if project_id is None:
            raise _error(status.HTTP_404_NOT_FOUND, "REVISION_NOT_FOUND")
        return project_id

    def validate_report(self, auth: AuthContext, revision_id: UUID) -> ReadinessView:
        project_id = self._project_id_for_revision(auth, revision_id)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            revision, _ = self._revision_and_report(
                session, auth, revision_id, Capability.VIEW_DRAFT_REPORT
            )
            result = validate_foundation_readiness(
                configuration_snapshot_id=str(revision.configuration_snapshot_id),
                report_data=revision.data,
            )
            return ReadinessView(
                state=result.state,
                can_submit=result.can_submit,
                issues=[asdict(issue) for issue in result.issues],
            )

    @staticmethod
    def _build_payload(
        report: DailyReport,
        revision: DailyReportRevision,
        snapshot: ConfigurationSnapshot,
        actor_id: UUID,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "template": {"key": "daily-fluids-report", "version": "1.0"},
            "payload_version": 1,
            "revision": {
                "number": revision.revision_number,
                "kind": revision.revision_kind,
                "state": "submitted",
                "based_on_revision_id": (
                    str(revision.based_on_revision_id) if revision.based_on_revision_id else None
                ),
            },
            "report": {
                "id": str(report.id),
                "number": report.report_number,
                "date": report.report_date.isoformat(),
                "state": "submitted",
            },
            "project_snapshot": deepcopy(snapshot.snapshot_json),
            "operations": deepcopy(revision.data),
            "reconciliation": {"readiness": {"state": "ready", "issues": []}},
            "approval": {
                "submitted_by": str(actor_id),
                "approved_by": None,
                "amendment_of": None,
            },
            "caveats": [],
        }

    def submit_report(
        self,
        auth: AuthContext,
        revision_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> ReportView:
        project_id = self._project_id_for_revision(auth, revision_id)
        request = {"revision_id": str(revision_id), "expected_version": expected_version}
        request_hash = _request_hash(request)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            existing = self._lock_idempotency(
                session, auth, "submit_report", idempotency_key, request_hash
            )
            if existing:
                return ReportView.model_validate(existing.response_json)
            revision, report = self._revision_and_report(
                session, auth, revision_id, Capability.SUBMIT_REPORT, lock=True
            )
            if revision.state not in {"draft", "ready_for_review"}:
                raise _error(status.HTTP_423_LOCKED, "REPORT_REVISION_LOCKED")
            if revision.row_version != expected_version:
                raise _error(status.HTTP_412_PRECONDITION_FAILED, "REPORT_VERSION_CONFLICT")
            readiness = validate_foundation_readiness(
                configuration_snapshot_id=str(revision.configuration_snapshot_id),
                report_data=revision.data,
            )
            if not readiness.can_submit:
                raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "REPORT_NOT_READY")
            snapshot = session.get(ConfigurationSnapshot, revision.configuration_snapshot_id)
            if snapshot is None:
                raise _error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "CONFIGURATION_SNAPSHOT_REQUIRED"
                )
            payload = self._build_payload(report, revision, snapshot, auth.user_id)
            checksum = payload_checksum(payload)
            before = {"state": revision.state, "version": revision.row_version}
            revision.state = "submitted"
            revision.submitted_by = auth.user_id
            report.aggregate_state = "under_review"
            report_payload = ReportPayload(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                daily_report_revision_id=revision.id,
                payload_json=payload,
                payload_schema_version="1.0",
                payload_checksum=checksum,
                template_key="daily-fluids-report",
                template_version="1.0",
            )
            session.add(report_payload)
            session.add(
                ReportDecision(
                    organisation_id=auth.organisation_id,
                    project_id=project_id,
                    daily_report_id=report.id,
                    daily_report_revision_id=revision.id,
                    action="submit",
                    actor_id=auth.user_id,
                    expected_payload_checksum=checksum,
                    from_state=before["state"],
                    to_state="submitted",
                )
            )
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="daily_report_revision",
                entity_id=revision.id,
                action="submit",
                before=before,
                after={"state": "submitted", "checksum": checksum},
            )
            session.flush()
            view = self._report_view(session, report)
            self._remember_idempotency(
                session,
                auth,
                "submit_report",
                idempotency_key,
                request_hash,
                "daily_report_revision",
                revision.id,
                view,
            )
            return view

    def reject_report(
        self, auth: AuthContext, revision_id: UUID, body: DecisionRequest
    ) -> ReportView:
        project_id = self._project_id_for_revision(auth, revision_id)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            revision, report = self._revision_and_report(
                session, auth, revision_id, Capability.REJECT_REPORT, lock=True
            )
            payload = session.scalar(
                select(ReportPayload).where(ReportPayload.daily_report_revision_id == revision.id)
            )
            if revision.state != "submitted" or payload is None:
                raise _error(status.HTTP_409_CONFLICT, "REPORT_NOT_CURRENT_SUBMISSION")
            if payload.payload_checksum != body.expected_checksum:
                raise _error(status.HTTP_409_CONFLICT, "REPORT_CHECKSUM_CONFLICT")
            if not body.reason or not body.reason.strip():
                raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "REJECTION_REASON_REQUIRED")
            revision.state = "rejected"
            revision.rejection_reason = body.reason.strip()
            new_draft = DailyReportRevision(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                daily_report_id=report.id,
                revision_number=revision.revision_number + 1,
                revision_kind="revision_after_rejection",
                state="draft",
                based_on_revision_id=revision.id,
                configuration_snapshot_id=revision.configuration_snapshot_id,
                data=deepcopy(revision.data),
            )
            session.add(new_draft)
            session.flush()
            report.aggregate_state = "draft"
            session.add(
                ReportDecision(
                    organisation_id=auth.organisation_id,
                    project_id=project_id,
                    daily_report_id=report.id,
                    daily_report_revision_id=revision.id,
                    action="reject",
                    actor_id=auth.user_id,
                    reason=body.reason.strip(),
                    expected_payload_checksum=payload.payload_checksum,
                    from_state="submitted",
                    to_state="rejected",
                )
            )
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="daily_report_revision",
                entity_id=revision.id,
                action="reject",
                before={"state": "submitted"},
                after={"state": "rejected", "new_draft_revision_id": str(new_draft.id)},
                reason=body.reason.strip(),
            )
            return self._report_view(session, report)

    def approve_report(
        self, auth: AuthContext, revision_id: UUID, body: DecisionRequest
    ) -> ReportView:
        project_id = self._project_id_for_revision(auth, revision_id)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            revision, report = self._revision_and_report(
                session, auth, revision_id, Capability.APPROVE_REPORT, lock=True
            )
            payload = session.scalar(
                select(ReportPayload).where(ReportPayload.daily_report_revision_id == revision.id)
            )
            if revision.state != "submitted" or payload is None:
                raise _error(status.HTTP_409_CONFLICT, "REPORT_NOT_CURRENT_SUBMISSION")
            if payload.payload_checksum != body.expected_checksum:
                raise _error(status.HTTP_409_CONFLICT, "REPORT_CHECKSUM_CONFLICT")
            if revision.submitted_by == auth.user_id:
                raise _error(status.HTTP_403_FORBIDDEN, "SELF_APPROVAL_DENIED")
            revision.state = "approved"
            revision.approved_by = auth.user_id
            report.aggregate_state = "approved"
            session.add(
                ReportDecision(
                    organisation_id=auth.organisation_id,
                    project_id=project_id,
                    daily_report_id=report.id,
                    daily_report_revision_id=revision.id,
                    action="approve",
                    actor_id=auth.user_id,
                    expected_payload_checksum=payload.payload_checksum,
                    from_state="submitted",
                    to_state="approved",
                )
            )
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="daily_report_revision",
                entity_id=revision.id,
                action="approve",
                before={"state": "submitted"},
                after={"state": "approved", "checksum": payload.payload_checksum},
            )
            return self._report_view(session, report)

    def audit_events(self, auth: AuthContext, project_id: UUID) -> list[dict[str, Any]]:
        with self._transaction(auth, project_ids=(project_id,)) as session:
            self._project(session, auth, project_id, Capability.VIEW_AUDIT)
            events = session.scalars(
                select(AuditEvent)
                .where(AuditEvent.project_id == project_id)
                .order_by(AuditEvent.occurred_at)
            ).all()
            return [
                {
                    "id": event.id,
                    "organisation_id": event.organisation_id,
                    "project_id": event.project_id,
                    "actor_id": event.actor_id,
                    "entity_type": event.entity_type,
                    "entity_id": event.entity_id,
                    "action": event.action,
                    "occurred_at": event.occurred_at,
                    "before": event.before_json,
                    "after": event.after_json,
                    "reason": event.reason,
                    "correlation_id": event.correlation_id,
                }
                for event in events
            ]

    def create_export(
        self,
        auth: AuthContext,
        revision_id: UUID,
        body: ExportRequest,
        idempotency_key: str,
    ) -> ExportView:
        project_id = self._project_id_for_revision(auth, revision_id)
        request = {"revision_id": str(revision_id), **body.model_dump()}
        request_hash = _request_hash(request)
        with self._transaction(auth, project_ids=(project_id,)) as session:
            existing = self._lock_idempotency(
                session, auth, "create_export", idempotency_key, request_hash
            )
            if existing:
                return ExportView.model_validate(existing.response_json)
            revision, _ = self._revision_and_report(
                session, auth, revision_id, Capability.EXPORT_REPORT
            )
            if revision.state != "approved":
                raise _error(status.HTTP_423_LOCKED, "APPROVED_REVISION_REQUIRED")
            payload = session.scalar(
                select(ReportPayload).where(ReportPayload.daily_report_revision_id == revision.id)
            )
            if payload is None:
                raise _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "FROZEN_PAYLOAD_MISSING")
            capabilities = self._database_capabilities(session, auth, project_id)
            required_visibility = (
                Capability.VIEW_INTERNAL_CONTENT
                if body.visibility == "internal"
                else Capability.VIEW_CLIENT_REPORT
            )
            if required_visibility not in capabilities:
                code = (
                    "INTERNAL_VISIBILITY_DENIED"
                    if body.visibility == "internal"
                    else "CAPABILITY_DENIED"
                )
                raise _error(status.HTTP_403_FORBIDDEN, code)
            if Capability.EXPORT_REPORT not in capabilities:
                raise _error(status.HTTP_403_FORBIDDEN, "CAPABILITY_DENIED")
            render_payload = filter_payload_visibility(payload.payload_json, body.visibility)
            artefact = render_report(body.format, render_payload, payload.payload_checksum)
            export = ReportExport(
                organisation_id=auth.organisation_id,
                project_id=project_id,
                payload_version_id=payload.id,
                export_type=body.format,
                visibility=body.visibility,
                export_kind="original",
                status="completed",
                binary_checksum=artefact.binary_checksum,
                template_version=artefact.template_version,
                renderer_version=artefact.renderer_version,
            )
            session.add(export)
            session.flush()
            view = ExportView(
                id=export.id,
                revision_id=revision.id,
                format=body.format,
                visibility=body.visibility,
                status=export.status,
                payload_checksum=payload.payload_checksum,
                binary_checksum=artefact.binary_checksum,
                template_version=artefact.template_version,
                renderer_version=artefact.renderer_version,
            )
            self._audit(
                session,
                auth,
                project_id=project_id,
                entity_type="report_export",
                entity_id=export.id,
                action="generate",
                before=None,
                after={
                    "payload_checksum": payload.payload_checksum,
                    "binary_checksum": artefact.binary_checksum,
                    "format": body.format,
                },
            )
            self._remember_idempotency(
                session,
                auth,
                "create_export",
                idempotency_key,
                request_hash,
                "report_export",
                export.id,
                view,
                202,
            )
            return view


postgres_repository = PostgresFoundationRepository()
