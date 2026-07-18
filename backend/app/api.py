from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from vantix_core.canonical import payload_checksum
from vantix_core.inventory import InventoryValidationError, build_opening_line, build_reversal_line
from vantix_core.lifecycle import (
    ConfigurationSnapshot,
    DailyReport,
    LifecycleError,
    ReportRevision,
)
from vantix_core.products import (
    ProductValidationError,
    canonicalise_product,
    select_effective_price,
)
from vantix_core.project_configuration import (
    ConfigurationActivationError,
    guard_configuration_activation,
    validate_project_configuration,
)

from .auth import AuthContext, Capability, auth_context
from .config import get_settings
from .postgres_repository import PostgresFoundationRepository, postgres_repository
from .renderers import render_report
from .schemas import (
    ConfigurationActivation,
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
    InventoryPostingView,
    InventoryReversalCreate,
    OpeningStockAuthorityProduct,
    OpeningStockAuthorityView,
    OpeningStockCreate,
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
from .store import ExportRecord, FoundationStore, IdempotencyConflict, ProjectRecord, store

router = APIRouter(prefix="/api/v1")
Repository = FoundationStore | PostgresFoundationRepository


def get_store() -> Repository:
    if get_settings().repository_backend == "postgres":
        return postgres_repository
    return store


def _project(project_id: UUID, auth: AuthContext, repository: FoundationStore) -> ProjectRecord:
    project = repository.projects.get(project_id)
    if not project or project.organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_NOT_FOUND"})
    return project


def _project_view(project: ProjectRecord) -> ProjectView:
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
        status="active" if project.active_snapshot else "draft",
        active_configuration_snapshot_id=(
            project.active_snapshot.id if project.active_snapshot else None
        ),
    )


def _memory_configuration(project: ProjectRecord, version_id: UUID) -> dict[str, Any]:
    record = next(
        (item for item in project.configuration_versions if item["id"] == version_id), None
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "CONFIGURATION_NOT_FOUND"})
    return record


def _memory_product_view(
    repository: FoundationStore, product: dict[str, Any], configuration_version: int
) -> ProjectProductView:
    prices = sorted(
        (
            price
            for price in repository.product_prices.values()
            if price["project_product_id"] == product["id"]
        ),
        key=lambda price: (price["effective_from"], str(price["id"])),
    )
    return ProjectProductView.model_validate(
        {
            **product,
            "configuration_row_version": configuration_version,
            "prices": prices,
        }
    )


def _memory_configuration_payload(
    repository: FoundationStore, project: ProjectRecord, record: dict[str, Any]
) -> dict[str, Any]:
    payload = deepcopy(cast(dict[str, Any], record["data"]))
    products = sorted(
        (
            product
            for product in repository.project_products.values()
            if product["configuration_version_id"] == record["id"]
        ),
        key=lambda product: (str(product["item_code"]).casefold(), str(product["id"])),
    )
    payload["products"] = [
        _memory_product_view(repository, product, cast(int, record["row_version"])).model_dump(
            mode="json",
            exclude={"project_id", "configuration_version_id", "configuration_row_version"},
            exclude_none=True,
        )
        for product in products
    ]
    return payload


def _product_http_error(exc: ProductValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": exc.code, "message": str(exc), "field": exc.field},
    )


def _report(report_id: UUID, auth: AuthContext, repository: FoundationStore) -> DailyReport:
    report = repository.reports.get(report_id)
    if not report or report.organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "REPORT_NOT_FOUND"})
    return report


def _report_for_revision(
    revision_id: UUID, auth: AuthContext, repository: FoundationStore
) -> DailyReport:
    report = next(
        (
            candidate
            for candidate in repository.reports.values()
            if any(revision.id == revision_id for revision in candidate.revisions)
        ),
        None,
    )
    if not report or report.organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "REVISION_NOT_FOUND"})
    return report


def _revision_view(revision: ReportRevision) -> RevisionView:
    return RevisionView(
        id=revision.id,
        number=revision.number,
        kind=revision.kind.value,
        state=revision.state.value,
        version=revision.version,
        data=revision.data,
        checksum=revision.checksum,
        based_on_revision_id=revision.based_on_revision_id,
    )


def _report_view(report: DailyReport) -> ReportView:
    return ReportView(
        id=report.id,
        project_id=report.project_id,
        report_date=report.report_date,
        report_number=report.report_number,
        revision=_revision_view(report.current_revision),
    )


def _domain_call[**P, R](function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    try:
        return function(*args, **kwargs)
    except LifecycleError as exc:
        code_map = {
            "REPORT_VERSION_CONFLICT": status.HTTP_412_PRECONDITION_FAILED,
            "REPORT_REVISION_LOCKED": status.HTTP_423_LOCKED,
            "SELF_APPROVAL_DENIED": status.HTTP_403_FORBIDDEN,
            "REPORT_NOT_READY": status.HTTP_422_UNPROCESSABLE_ENTITY,
        }
        raise HTTPException(
            code_map.get(exc.code, status.HTTP_409_CONFLICT),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


def _request_hash(value: dict[str, Any]) -> str:
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def _idempotent[R](
    repository: FoundationStore,
    auth: AuthContext,
    operation_type: str,
    idempotency_key: str,
    request: dict[str, Any],
    operation: Callable[[], R],
) -> R:
    try:
        return repository.idempotent(
            organisation_id=auth.organisation_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(request),
            operation=operation,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "Key reused with a different request.",
            },
        ) from exc


@router.post("/organisations", response_model=OrganisationView, status_code=201)
def create_organisation(
    body: OrganisationCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> OrganisationView:
    auth.require(Capability.CREATE_PROJECT)
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_organisation(auth, body)
    record = repository.create_organisation(body.name)
    return OrganisationView(id=record.id, name=record.name)


@router.post(
    "/organisations/{organisation_id}/projects", response_model=ProjectView, status_code=201
)
def create_project(
    organisation_id: UUID,
    body: ProjectCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_project(auth, body, organisation_id)
    auth.require(Capability.CREATE_PROJECT)
    if organisation_id != auth.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "ORGANISATION_NOT_FOUND"})
    record = repository.create_project(organisation_id, **body.model_dump())
    return ProjectView(**body.model_dump(), id=record.id, organisation_id=record.organisation_id)


@router.get("/projects", response_model=list[ProjectView])
def list_projects(
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> list[ProjectView]:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.list_projects(auth)
    return [
        _project_view(project)
        for project in repository.projects.values()
        if project.organisation_id == auth.organisation_id
    ]


@router.get("/projects/{project_id}", response_model=ProjectView)
def get_project(
    project_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.get_project(auth, project_id)
    project = _project(project_id, auth, repository)
    return _project_view(project)


@router.post(
    "/projects/{project_id}/configuration-versions",
    response_model=ConfigurationView,
    status_code=201,
)
def create_configuration(
    project_id: UUID,
    body: ConfigurationCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ConfigurationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_configuration(auth, project_id, body, idempotency_key)
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    request = {"project_id": str(project_id), **body.model_dump(mode="json")}

    def create() -> ConfigurationView:
        if any(item["state"] == "draft" for item in project.configuration_versions):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "CONFIGURATION_DRAFT_EXISTS"},
            )
        version = len(project.configuration_versions) + 1
        active = next(
            (item for item in project.configuration_versions if item["state"] == "active"), None
        )
        if body.data is not None:
            data = body.data.model_dump(mode="json", exclude_none=True)
        elif body.copy_active and active is not None:
            data = deepcopy(cast(dict[str, Any], active["data"]))
        else:
            data = {"default_interval_id": None, "intervals": []}
        record = {
            "id": uuid4(),
            "version": version,
            "state": "draft",
            "row_version": 1,
            "data": data,
        }
        project.configuration_versions.append(record)
        if body.data is None and body.copy_active and active is not None:
            active_products = [
                product
                for product in repository.project_products.values()
                if product["configuration_version_id"] == active["id"]
            ]
            for source in active_products:
                source_id = cast(UUID, source["id"])
                copied_id = uuid4()
                repository.project_products[copied_id] = {
                    **deepcopy(source),
                    "id": copied_id,
                    "configuration_version_id": record["id"],
                }
                for price in list(repository.product_prices.values()):
                    if price["project_product_id"] == source_id:
                        copied_price_id = uuid4()
                        repository.product_prices[copied_price_id] = {
                            **deepcopy(price),
                            "id": copied_price_id,
                            "project_product_id": copied_id,
                        }
        return ConfigurationView(
            id=cast(UUID, record["id"]),
            project_id=project.id,
            version=cast(int, record["version"]),
            state=cast(Any, record["state"]),
            row_version=1,
            data=data,
        )

    return _idempotent(
        repository,
        auth,
        "create_configuration",
        idempotency_key,
        request,
        create,
    )


@router.get("/projects/{project_id}/configuration-versions", response_model=list[ConfigurationView])
def list_configurations(
    project_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> list[ConfigurationView]:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.list_configurations(auth, project_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail={"code": "POSTGRES_REQUIRED"})


@router.get(
    "/projects/{project_id}/configuration-versions/{version_id}",
    response_model=ConfigurationView,
)
def get_configuration(
    project_id: UUID,
    version_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ConfigurationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.get_configuration(auth, project_id, version_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail={"code": "POSTGRES_REQUIRED"})


@router.patch(
    "/projects/{project_id}/configuration-versions/{version_id}",
    response_model=ConfigurationView,
)
def patch_configuration(
    project_id: UUID,
    version_id: UUID,
    body: ConfigurationPatch,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ConfigurationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.patch_configuration(auth, project_id, version_id, body)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail={"code": "POSTGRES_REQUIRED"})


@router.post(
    "/projects/{project_id}/configuration-versions/{version_id}/validate",
    response_model=ConfigurationReadinessView,
)
def validate_configuration(
    project_id: UUID,
    version_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ConfigurationReadinessView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.validate_configuration(auth, project_id, version_id)
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    record = _memory_configuration(project, version_id)
    payload = _memory_configuration_payload(repository, project, record)
    readiness = validate_project_configuration(
        {
            "project_code": project.project_code,
            "project_name": project.project_name,
            "well_name": project.well_name,
            "time_zone": project.time_zone,
            "currency": project.currency,
            "unit_set": project.unit_set,
        },
        payload,
    )
    return ConfigurationReadinessView(
        state=readiness.state,
        can_activate=readiness.can_activate,
        validated_version=cast(int, record["row_version"]),
        draft_checksum=payload_checksum(payload),
        issues=[asdict(issue) for issue in readiness.issues],
    )


@router.post(
    "/projects/{project_id}/configuration-versions/{version_id}/activate",
    response_model=ConfigurationView,
)
def activate_configuration(
    project_id: UUID,
    version_id: UUID,
    body: ConfigurationActivation,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ConfigurationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.activate_configuration(
            auth,
            project_id,
            version_id,
            idempotency_key,
            body.expected_version,
            body.expected_checksum,
        )
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    record = next(
        (item for item in project.configuration_versions if item["id"] == version_id), None
    )
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "CONFIGURATION_NOT_FOUND"})

    def activate() -> ConfigurationView:
        payload = _memory_configuration_payload(repository, project, record)
        try:
            guard_configuration_activation(
                project={
                    "project_code": project.project_code,
                    "project_name": project.project_name,
                    "well_name": project.well_name,
                    "time_zone": project.time_zone,
                    "currency": project.currency,
                    "unit_set": project.unit_set,
                },
                data=payload,
                state=cast(str, record["state"]),
                row_version=cast(int, record["row_version"]),
                expected_version=body.expected_version,
                expected_checksum=body.expected_checksum,
                version_number=cast(int, record["version"]),
                latest_version_number=max(
                    cast(int, item["version"]) for item in project.configuration_versions
                ),
                active_version_number=(
                    project.active_snapshot.version if project.active_snapshot else None
                ),
            )
        except ConfigurationActivationError as exc:
            status_codes = {
                "CONFIGURATION_VERSION_CONFLICT": status.HTTP_412_PRECONDITION_FAILED,
                "CONFIGURATION_NOT_READY": status.HTTP_422_UNPROCESSABLE_ENTITY,
            }
            raise HTTPException(
                status_codes.get(exc.code, status.HTTP_409_CONFLICT),
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        snapshot = ConfigurationSnapshot.create(
            project.id,
            cast(int, record["version"]),
            payload,
        )
        for item in project.configuration_versions:
            if item["state"] == "active":
                item["state"] = "superseded"
        record["state"] = "active"
        project.active_snapshot = snapshot
        return ConfigurationView(
            id=cast(UUID, record["id"]),
            project_id=project.id,
            version=cast(int, record["version"]),
            state=cast(Any, record["state"]),
            row_version=cast(int, record["row_version"]),
            data=cast(dict[str, Any], record["data"]),
            snapshot_id=snapshot.id,
            checksum=snapshot.checksum,
        )

    return _idempotent(
        repository,
        auth,
        "activate_configuration",
        idempotency_key,
        {
            "project_id": str(project_id),
            "version_id": str(version_id),
            **body.model_dump(),
        },
        activate,
    )


@router.get("/projects/{project_id}/products", response_model=list[ProjectProductView])
def list_products(
    project_id: UUID,
    configuration_version_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> list[ProjectProductView]:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.list_products(auth, project_id, configuration_version_id)
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    record = _memory_configuration(project, configuration_version_id)
    products = sorted(
        (
            product
            for product in repository.project_products.values()
            if product["configuration_version_id"] == configuration_version_id
        ),
        key=lambda product: (str(product["item_code"]).casefold(), str(product["id"])),
    )
    return [
        _memory_product_view(repository, product, cast(int, record["row_version"]))
        for product in products
    ]


@router.post("/projects/{project_id}/products", response_model=ProjectProductView, status_code=201)
def create_product(
    project_id: UUID,
    body: ProjectProductCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectProductView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_product(auth, project_id, body)
    auth.require(Capability.CONFIGURE_PROJECT)
    project = _project(project_id, auth, repository)
    record = _memory_configuration(project, body.configuration_version_id)
    if record["state"] != "draft":
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "CONFIGURATION_LOCKED"})
    if record["row_version"] != body.expected_configuration_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "CONFIGURATION_VERSION_CONFLICT"},
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
        raise _product_http_error(exc) from exc
    if any(
        product["configuration_version_id"] == body.configuration_version_id
        and str(product["item_code"]).casefold() == str(canonical["item_code"]).casefold()
        for product in repository.project_products.values()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "PRODUCT_CODE_EXISTS"})
    stored = {
        **canonical,
        "id": product_id,
        "project_id": project_id,
        "configuration_version_id": body.configuration_version_id,
    }
    stored.pop("prices", None)
    repository.project_products[product_id] = stored
    record["row_version"] = cast(int, record["row_version"]) + 1
    return _memory_product_view(repository, stored, cast(int, record["row_version"]))


@router.patch("/project-products/{product_id}", response_model=ProjectProductView)
def patch_product(
    product_id: UUID,
    body: ProjectProductPatch,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectProductView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.patch_product(auth, product_id, body)
    auth.require(Capability.CONFIGURE_PROJECT)
    product = repository.project_products.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_PRODUCT_NOT_FOUND"})
    project = _project(cast(UUID, product["project_id"]), auth, repository)
    record = _memory_configuration(project, cast(UUID, product["configuration_version_id"]))
    if record["state"] != "draft":
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "CONFIGURATION_LOCKED"})
    if record["row_version"] != body.expected_configuration_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "CONFIGURATION_VERSION_CONFLICT"},
        )
    current = _memory_product_view(
        repository, product, cast(int, record["row_version"])
    ).model_dump(
        mode="json",
        exclude={"project_id", "configuration_version_id", "configuration_row_version"},
        exclude_none=True,
    )
    values = body.model_dump(
        mode="json", exclude={"expected_configuration_version"}, exclude_none=True
    )
    try:
        canonical = canonicalise_product(
            {
                "id": str(product_id),
                "product_definition_id": str(product["product_definition_id"]),
                **values,
                "prices": current["prices"],
            },
            project.currency,
            require_price=False,
        )
    except ProductValidationError as exc:
        raise _product_http_error(exc) from exc
    if any(
        candidate["id"] != product_id
        and candidate["configuration_version_id"] == product["configuration_version_id"]
        and str(candidate["item_code"]).casefold() == str(canonical["item_code"]).casefold()
        for candidate in repository.project_products.values()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "PRODUCT_CODE_EXISTS"})
    canonical.pop("prices")
    product.update(canonical)
    product["id"] = product_id
    record["row_version"] = cast(int, record["row_version"]) + 1
    return _memory_product_view(repository, product, cast(int, record["row_version"]))


@router.delete("/project-products/{product_id}", response_model=ConfigurationMutationView)
def delete_product(
    product_id: UUID,
    body: ConfigurationVersionExpectation,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ConfigurationMutationView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.delete_product(auth, product_id, body)
    auth.require(Capability.CONFIGURE_PROJECT)
    product = repository.project_products.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_PRODUCT_NOT_FOUND"})
    project = _project(cast(UUID, product["project_id"]), auth, repository)
    record = _memory_configuration(project, cast(UUID, product["configuration_version_id"]))
    if record["state"] != "draft":
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "CONFIGURATION_LOCKED"})
    if record["row_version"] != body.expected_configuration_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "CONFIGURATION_VERSION_CONFLICT"},
        )
    for price_id in [
        key
        for key, price in repository.product_prices.items()
        if price["project_product_id"] == product_id
    ]:
        del repository.product_prices[price_id]
    del repository.project_products[product_id]
    record["row_version"] = cast(int, record["row_version"]) + 1
    return ConfigurationMutationView(configuration_row_version=cast(int, record["row_version"]))


@router.post(
    "/project-products/{product_id}/prices",
    response_model=ProjectProductView,
    status_code=201,
)
def create_product_price(
    product_id: UUID,
    body: ProductPriceCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectProductView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_product_price(auth, product_id, body)
    product = repository.project_products.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_PRODUCT_NOT_FOUND"})
    project = _project(cast(UUID, product["project_id"]), auth, repository)
    auth.require(Capability.CONFIGURE_PROJECT)
    record = _memory_configuration(project, cast(UUID, product["configuration_version_id"]))
    if record["state"] != "draft":
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "CONFIGURATION_LOCKED"})
    if record["row_version"] != body.expected_configuration_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "CONFIGURATION_VERSION_CONFLICT"},
        )
    price_id = uuid4()
    view = _memory_product_view(repository, product, cast(int, record["row_version"]))
    candidate = view.model_dump(
        mode="json",
        exclude={"project_id", "configuration_version_id", "configuration_row_version"},
        exclude_none=True,
    )
    candidate_price = {
        "id": str(price_id),
        **body.model_dump(
            mode="json", exclude={"expected_configuration_version"}, exclude_none=True
        ),
    }
    candidate["prices"] = [*candidate["prices"], candidate_price]
    try:
        canonical = canonicalise_product(candidate, project.currency, require_price=False)
    except ProductValidationError as exc:
        raise _product_http_error(exc) from exc
    stored_price = next(item for item in canonical["prices"] if item["id"] == str(price_id))
    repository.product_prices[price_id] = {
        **stored_price,
        "id": price_id,
        "project_product_id": product_id,
    }
    record["row_version"] = cast(int, record["row_version"]) + 1
    return _memory_product_view(repository, product, cast(int, record["row_version"]))


@router.get("/project-products/{product_id}/price-at", response_model=ProductPriceView)
def get_product_price_at(
    product_id: UUID,
    date_at: date = Query(alias="date"),
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProductPriceView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.price_at(auth, product_id, date_at)
    product = repository.project_products.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_PRODUCT_NOT_FOUND"})
    _project(cast(UUID, product["project_id"]), auth, repository)
    prices = [
        price
        for price in repository.product_prices.values()
        if price["project_product_id"] == product_id
    ]
    selected = select_effective_price(prices, date_at)
    if selected is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PRICE_NOT_EFFECTIVE"})
    return ProductPriceView.model_validate(selected)


def _memory_active_products(
    repository: FoundationStore, project: ProjectRecord
) -> list[dict[str, Any]]:
    if project.active_snapshot is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "ACTIVE_CONFIGURATION_REQUIRED"}
        )
    configuration = next(
        (
            item
            for item in project.configuration_versions
            if item["version"] == project.active_snapshot.version
        ),
        None,
    )
    if configuration is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "ACTIVE_CONFIGURATION_REQUIRED"}
        )
    return [
        product
        for product in repository.project_products.values()
        if product["configuration_version_id"] == configuration["id"]
        and product["inventory_applicable"]
        and product["active"]
    ]


@router.get(
    "/projects/{project_id}/inventory/opening-stock-authority",
    response_model=OpeningStockAuthorityView,
)
def opening_stock_authority(
    project_id: UUID,
    posting_date: date,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> OpeningStockAuthorityView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.opening_stock_authority(auth, project_id, posting_date)
    if not auth.capabilities.intersection({Capability.VIEW_INVENTORY, Capability.POST_INVENTORY}):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CAPABILITY_DENIED"})
    project = _project(project_id, auth, repository)
    products = sorted(
        _memory_active_products(repository, project), key=lambda item: str(item["item_code"])
    )
    assert project.active_snapshot is not None
    return OpeningStockAuthorityView(
        project_id=project_id,
        posting_date=posting_date,
        configuration_snapshot_id=project.active_snapshot.id,
        products=[
            OpeningStockAuthorityProduct(
                product_definition_id=product["product_definition_id"],
                configuration_product_version_id=product["id"],
                item_code=product["item_code"],
                item_name=product["item_name"],
                package_size=str(product["package_size"]),
                package_unit_code=product["package_unit_code"],
                inventory_unit_code=product["inventory_unit_code"],
                price=(
                    ProductPriceView.model_validate(selected)
                    if (
                        selected := select_effective_price(
                            [
                                price
                                for price in repository.product_prices.values()
                                if price["project_product_id"] == product["id"]
                            ],
                            posting_date,
                        )
                    )
                    else None
                ),
            )
            for product in products
        ],
    )


@router.post(
    "/projects/{project_id}/inventory-postings/opening-stock",
    response_model=InventoryPostingView,
    status_code=201,
)
def post_opening_stock(
    project_id: UUID,
    body: OpeningStockCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> InventoryPostingView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.post_opening_stock(auth, project_id, body, idempotency_key)
    auth.require(Capability.POST_INVENTORY)
    project = _project(project_id, auth, repository)
    request_hash = _request_hash({"project_id": str(project_id), **body.model_dump(mode="json")})

    def post() -> InventoryPostingView:
        if any(
            item["project_id"] == project_id
            and item["posting_type"] == "opening_stock"
            and item.get("reversal_posting_id") is None
            for item in repository.inventory_postings.values()
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail={"code": "OPENING_STOCK_ALREADY_POSTED"}
            )
        products = {
            UUID(str(item["product_definition_id"])): item
            for item in _memory_active_products(repository, project)
        }
        if len(body.lines) != len({line.product_definition_id for line in body.lines}):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "DUPLICATE_OPENING_PRODUCT"}
            )
        if any(line.product_definition_id not in products for line in body.lines):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "OPENING_PRODUCT_NOT_AUTHORISED"},
            )
        assert project.active_snapshot is not None
        posting_id = uuid4()
        now = datetime.now(UTC)
        lines: list[dict[str, Any]] = []
        for request_line in body.lines:
            product = products[request_line.product_definition_id]
            price = select_effective_price(
                [
                    value
                    for value in repository.product_prices.values()
                    if value["project_product_id"] == product["id"]
                ],
                body.posting_date,
            )
            frozen_product = {
                key: product.get(key)
                for key in (
                    "item_code",
                    "item_name",
                    "packaging",
                    "package_size",
                    "package_unit_code",
                    "inventory_unit_code",
                    "specific_gravity",
                )
            }
            try:
                frozen = build_opening_line(
                    entered_quantity=request_line.entered_quantity,
                    entered_unit_code=request_line.entered_unit_code,
                    product=frozen_product,
                    price=price,
                )
            except InventoryValidationError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": exc.code, "message": str(exc), "field": exc.field},
                ) from exc
            line_id = uuid4()
            line = {
                "id": line_id,
                "product_definition_id": product["product_definition_id"],
                "configuration_product_version_id": product["id"],
                **frozen,
                "frozen_product": deepcopy(frozen_product),
            }
            lines.append(line)
            repository.inventory_lines[line_id] = {**line, "posting_id": posting_id}
        stored = {
            "id": posting_id,
            "project_id": project_id,
            "source_configuration_snapshot_id": project.active_snapshot.id,
            "posting_type": "opening_stock",
            "status": "posted",
            "posting_date": body.posting_date,
            "reversal_of_posting_id": None,
            "reversal_posting_id": None,
            "reason": None,
            "posted_by": auth.user_id,
            "posted_at": now,
            "lines": lines,
        }
        repository.inventory_postings[posting_id] = stored
        return InventoryPostingView.model_validate(stored)

    try:
        return repository.idempotent(
            organisation_id=auth.organisation_id,
            operation_type="post_opening_stock",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=post,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "IDEMPOTENCY_KEY_REUSED"}
        ) from exc


@router.get("/projects/{project_id}/inventory-postings", response_model=list[InventoryPostingView])
def list_inventory_postings(
    project_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> list[InventoryPostingView]:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.list_inventory_postings(auth, project_id)
    if not auth.capabilities.intersection({Capability.VIEW_INVENTORY, Capability.POST_INVENTORY}):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CAPABILITY_DENIED"})
    _project(project_id, auth, repository)
    return [
        InventoryPostingView.model_validate(item)
        for item in sorted(
            (
                item
                for item in repository.inventory_postings.values()
                if item["project_id"] == project_id
            ),
            key=lambda item: (item["posting_date"], item["posted_at"]),
        )
    ]


@router.post(
    "/projects/{project_id}/inventory-postings/{posting_id}/reversals",
    response_model=InventoryPostingView,
    status_code=201,
)
def reverse_inventory_posting(
    project_id: UUID,
    posting_id: UUID,
    body: InventoryReversalCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> InventoryPostingView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.reverse_inventory_posting(
            auth, project_id, posting_id, body, idempotency_key
        )
    auth.require(Capability.POST_INVENTORY)
    _project(project_id, auth, repository)
    request_hash = _request_hash(
        {
            "project_id": str(project_id),
            "posting_id": str(posting_id),
            **body.model_dump(mode="json"),
        }
    )

    def reverse() -> InventoryPostingView:
        original = repository.inventory_postings.get(posting_id)
        if (
            not original
            or original["project_id"] != project_id
            or original["posting_type"] != "opening_stock"
        ):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail={"code": "INVENTORY_POSTING_NOT_REVERSIBLE"}
            )
        if original.get("reversal_posting_id"):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail={"code": "INVENTORY_POSTING_ALREADY_REVERSED"}
            )
        if body.posting_date < original["posting_date"]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "REVERSAL_DATE_PRECEDES_ORIGINAL"},
            )
        reversal_id = uuid4()
        lines = []
        for source in original["lines"]:
            frozen = build_reversal_line(source)
            line_id = uuid4()
            line = {**source, **frozen, "id": line_id}
            lines.append(line)
            repository.inventory_lines[line_id] = {**line, "posting_id": reversal_id}
        stored = {
            "id": reversal_id,
            "project_id": project_id,
            "source_configuration_snapshot_id": original["source_configuration_snapshot_id"],
            "posting_type": "reversal",
            "status": "posted",
            "posting_date": body.posting_date,
            "reversal_of_posting_id": posting_id,
            "reversal_posting_id": None,
            "reason": body.reason,
            "posted_by": auth.user_id,
            "posted_at": datetime.now(UTC),
            "lines": lines,
        }
        original["reversal_posting_id"] = reversal_id
        repository.inventory_postings[reversal_id] = stored
        return InventoryPostingView.model_validate(stored)

    try:
        return repository.idempotent(
            organisation_id=auth.organisation_id,
            operation_type="reverse_inventory_posting",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=reverse,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "IDEMPOTENCY_KEY_REUSED"}
        ) from exc


@router.patch("/product-prices/{price_id}", response_model=ProjectProductView)
def patch_product_price(
    price_id: UUID,
    body: ProductPricePatch,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectProductView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.patch_product_price(auth, price_id, body)
    price = repository.product_prices.get(price_id)
    if price is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PRODUCT_PRICE_NOT_FOUND"})
    product_id = cast(UUID, price["project_product_id"])
    product = repository.project_products[product_id]
    project = _project(cast(UUID, product["project_id"]), auth, repository)
    auth.require(Capability.CONFIGURE_PROJECT)
    record = _memory_configuration(project, cast(UUID, product["configuration_version_id"]))
    if record["state"] != "draft":
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "CONFIGURATION_LOCKED"})
    if record["row_version"] != body.expected_configuration_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "CONFIGURATION_VERSION_CONFLICT"},
        )
    view = _memory_product_view(repository, product, cast(int, record["row_version"]))
    candidate = view.model_dump(
        mode="json",
        exclude={"project_id", "configuration_version_id", "configuration_row_version"},
        exclude_none=True,
    )
    replacement = {
        "id": str(price_id),
        **body.model_dump(
            mode="json", exclude={"expected_configuration_version"}, exclude_none=True
        ),
    }
    candidate["prices"] = [
        replacement if item["id"] == str(price_id) else item for item in candidate["prices"]
    ]
    try:
        canonical = canonicalise_product(candidate, project.currency, require_price=False)
    except ProductValidationError as exc:
        raise _product_http_error(exc) from exc
    updated = next(item for item in canonical["prices"] if item["id"] == str(price_id))
    repository.product_prices[price_id] = {
        **updated,
        "id": price_id,
        "project_product_id": product_id,
    }
    record["row_version"] = cast(int, record["row_version"]) + 1
    return _memory_product_view(repository, product, cast(int, record["row_version"]))


@router.delete("/product-prices/{price_id}", response_model=ProjectProductView)
def delete_product_price(
    price_id: UUID,
    body: ConfigurationVersionExpectation,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ProjectProductView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.delete_product_price(auth, price_id, body)
    price = repository.product_prices.get(price_id)
    if price is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PRODUCT_PRICE_NOT_FOUND"})
    product_id = cast(UUID, price["project_product_id"])
    product = repository.project_products[product_id]
    project = _project(cast(UUID, product["project_id"]), auth, repository)
    auth.require(Capability.CONFIGURE_PROJECT)
    record = _memory_configuration(project, cast(UUID, product["configuration_version_id"]))
    if record["state"] != "draft":
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "CONFIGURATION_LOCKED"})
    if record["row_version"] != body.expected_configuration_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "CONFIGURATION_VERSION_CONFLICT"},
        )
    del repository.product_prices[price_id]
    record["row_version"] = cast(int, record["row_version"]) + 1
    return _memory_product_view(repository, product, cast(int, record["row_version"]))


@router.post("/projects/{project_id}/daily-reports", response_model=ReportView, status_code=201)
def create_daily_report(
    project_id: UUID,
    body: DailyReportCreate,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_daily_report(auth, project_id, body, idempotency_key)
    auth.require(Capability.EDIT_REPORT)
    project = _project(project_id, auth, repository)
    if not project.active_snapshot:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "ACTIVE_CONFIGURATION_REQUIRED"}
        )

    def create() -> ReportView:
        if any(
            report.project_id == project_id and report.report_date == body.report_date.isoformat()
            for report in repository.reports.values()
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "REPORT_DATE_CONFLICT"})
        assert project.active_snapshot is not None
        report = DailyReport.create(
            organisation_id=auth.organisation_id,
            project_id=project_id,
            report_date=body.report_date.isoformat(),
            report_number=body.report_number,
            configuration_snapshot=project.active_snapshot,
            actor_id=auth.user_id,
        )
        repository.reports[report.id] = report
        return _report_view(report)

    return _idempotent(
        repository,
        auth,
        "create_daily_report",
        idempotency_key,
        {"project_id": str(project_id), **body.model_dump(mode="json")},
        create,
    )


@router.patch(
    "/daily-report-revisions/{revision_id}/sections/{section_key}", response_model=ReportView
)
def patch_section(
    revision_id: UUID,
    section_key: str,
    body: DraftPatch,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.patch_section(auth, revision_id, section_key, body)
    auth.require(Capability.EDIT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    if report.current_revision.id != revision_id:
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "REPORT_REVISION_LOCKED"})
    _domain_call(
        report.edit,
        {section_key: body.data},
        expected_version=body.expected_version,
        actor_id=auth.user_id,
    )
    return _report_view(report)


@router.post("/daily-report-revisions/{revision_id}/validate", response_model=ReadinessView)
def validate_report(
    revision_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReadinessView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.validate_report(auth, revision_id)
    auth.require(Capability.VIEW_DRAFT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    result = report.current_revision.readiness()
    return ReadinessView(
        state=result.state,
        can_submit=result.can_submit,
        issues=[asdict(issue) for issue in result.issues],
    )


@router.post("/daily-report-revisions/{revision_id}/submit", response_model=ReportView)
def submit_report(
    revision_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    if_match: str = Header(alias="If-Match"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ReportView:
    try:
        version = int(if_match.strip('"'))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_IF_MATCH"}
        ) from exc
    if isinstance(repository, PostgresFoundationRepository):
        return repository.submit_report(auth, revision_id, version, idempotency_key)
    auth.require(Capability.SUBMIT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)

    def submit() -> ReportView:
        _domain_call(report.submit, expected_version=version, actor_id=auth.user_id)
        return _report_view(report)

    return _idempotent(
        repository,
        auth,
        "submit_report",
        idempotency_key,
        {"revision_id": str(revision_id), "expected_version": version},
        submit,
    )


@router.post("/daily-report-revisions/{revision_id}/reject", response_model=ReportView)
def reject_report(
    revision_id: UUID,
    body: DecisionRequest,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.reject_report(auth, revision_id, body)
    auth.require(Capability.REJECT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    _domain_call(
        report.reject,
        submitted_revision_id=revision_id,
        expected_checksum=body.expected_checksum,
        actor_id=auth.user_id,
        reason=body.reason or "",
    )
    return _report_view(report)


@router.post("/daily-report-revisions/{revision_id}/approve", response_model=ReportView)
def approve_report(
    revision_id: UUID,
    body: DecisionRequest,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.approve_report(auth, revision_id, body)
    auth.require(Capability.APPROVE_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    _domain_call(
        report.approve,
        submitted_revision_id=revision_id,
        expected_checksum=body.expected_checksum,
        actor_id=auth.user_id,
    )
    return _report_view(report)


@router.get("/projects/{project_id}/audit-events")
def audit_events(
    project_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> list[dict[str, Any]]:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.audit_events(auth, project_id)
    auth.require(Capability.VIEW_AUDIT)
    _project(project_id, auth, repository)
    return [
        asdict(event)
        for report in repository.reports.values()
        if report.project_id == project_id
        for event in report.audit_events
    ]


@router.get("/daily-reports/{report_id}", response_model=ReportView)
def get_daily_report(
    report_id: UUID,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
) -> ReportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.get_report(auth, report_id)
    auth.require(Capability.VIEW_CLIENT_REPORT)
    return _report_view(_report(report_id, auth, repository))


@router.post(
    "/daily-report-revisions/{revision_id}/exports", response_model=ExportView, status_code=202
)
def create_export(
    revision_id: UUID,
    body: ExportRequest,
    auth: AuthContext = Depends(auth_context),
    repository: Repository = Depends(get_store),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ExportView:
    if isinstance(repository, PostgresFoundationRepository):
        return repository.create_export(auth, revision_id, body, idempotency_key)
    auth.require(Capability.EXPORT_REPORT)
    report = _report_for_revision(revision_id, auth, repository)
    revision = report.current_revision
    if revision.state.value != "approved" or not revision.checksum:
        raise HTTPException(status.HTTP_423_LOCKED, detail={"code": "APPROVED_REVISION_REQUIRED"})
    if revision.payload is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "FROZEN_PAYLOAD_MISSING"},
        )

    def generate() -> ExportView:
        assert revision.payload is not None and revision.checksum is not None
        artefact = render_report(body.format, revision.payload, revision.checksum)
        record = ExportRecord(
            uuid4(),
            revision.id,
            body.format,
            body.visibility,
            "completed",
            revision.checksum,
            artefact.binary_checksum,
            artefact.template_version,
            artefact.renderer_version,
            artefact.content,
        )
        repository.exports[record.id] = record
        visible = {key: value for key, value in asdict(record).items() if key != "content"}
        return ExportView(**visible)

    return _idempotent(
        repository,
        auth,
        "create_export",
        idempotency_key,
        {"revision_id": str(revision.id), **body.model_dump()},
        generate,
    )
