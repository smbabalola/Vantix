from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient

from .config import Settings, get_settings


class Capability(StrEnum):
    CREATE_PROJECT = "create_project"
    CONFIGURE_PROJECT = "configure_project"
    VIEW_DRAFT_REPORT = "view_draft_report"
    VIEW_CLIENT_REPORT = "view_client_report"
    VIEW_INTERNAL_CONTENT = "view_internal_content"
    EDIT_REPORT = "edit_report"
    SUBMIT_REPORT = "submit_report"
    REJECT_REPORT = "reject_report"
    APPROVE_REPORT = "approve_report"
    VIEW_AUDIT = "view_audit"
    EXPORT_REPORT = "export_report"
    VIEW_INVENTORY = "view_inventory"
    POST_INVENTORY = "post_inventory"


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: UUID
    organisation_id: UUID
    capabilities: frozenset[Capability]

    def require(self, capability: Capability) -> None:
        if capability not in self.capabilities:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "CAPABILITY_DENIED"})


def _development_context(
    user_id: str | None,
    organisation_id: str | None,
    capabilities: str | None,
) -> AuthContext | None:
    if not user_id or not organisation_id:
        return None
    try:
        parsed = frozenset(
            Capability(item.strip()) for item in (capabilities or "").split(",") if item.strip()
        )
        return AuthContext(UUID(user_id), UUID(organisation_id), parsed)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_DEV_AUTH"}
        ) from exc


def _verify_oidc(token: str, settings: Settings) -> dict[str, object]:
    if not settings.oidc_jwks_url or not settings.oidc_issuer:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "OIDC_NOT_CONFIGURED"}
        )
    try:
        key = PyJWKClient(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        return cast(
            dict[str, object],
            jwt.decode(
                token,
                key.key,
                algorithms=["RS256", "ES256"],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
            ),
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_ACCESS_TOKEN"}
        ) from exc


async def auth_context(
    request: Request,
    settings: Settings = Depends(get_settings),
    x_vantix_user_id: str | None = Header(default=None),
    x_vantix_organisation_id: str | None = Header(default=None),
    x_vantix_capabilities: str | None = Header(default=None),
) -> AuthContext:
    if settings.environment in {"development", "test"} and settings.allow_development_auth:
        context = _development_context(
            x_vantix_user_id,
            x_vantix_organisation_id,
            x_vantix_capabilities,
        )
        if context:
            return context

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail={"code": "AUTHENTICATION_REQUIRED"}
        )
    claims = _verify_oidc(authorization.removeprefix("Bearer ").strip(), settings)
    try:
        # Membership resolution will replace these trusted custom claims in the DB adapter.
        capabilities_claim = claims.get("vantix_capabilities", [])
        if not isinstance(capabilities_claim, list):
            raise TypeError("vantix_capabilities must be a list")
        return AuthContext(
            UUID(str(claims["vantix_user_id"])),
            UUID(str(claims["vantix_organisation_id"])),
            frozenset(Capability(str(item)) for item in capabilities_claim),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail={"code": "IDENTITY_NOT_MAPPED"}
        ) from exc
