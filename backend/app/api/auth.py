"""FastAPI authentication/authorization dependencies (T019).

- `get_principal` authenticates the bearer token (401 on failure, with
  `WWW-Authenticate: Bearer`).
- `require_roles(...)` is the authorization stage: an authenticated principal
  lacking every listed role is denied `403` — never `401` (security-boundary.md
  Failure semantics).
- `authorize_object_read` enforces the per-object rows of the authorization
  matrix for submitter/adjudicator/auditor reads.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db.enums import ModelStatus, Role, Verdict
from app.db.models import EvaluationRun, ModelVersion
from app.services import auth as auth_service
from app.services.config import AppConfig, load_config


def get_config() -> AppConfig:
    return load_config()


def get_request_id(request: Request) -> str:
    rid = request.headers.get("X-Request-ID") or request.state.__dict__.get("request_id")
    if not rid:
        rid = uuid.uuid4().hex
    request.state.request_id = rid
    return rid


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    return token.strip()


def get_principal(
    request: Request, cfg: AppConfig = Depends(get_config)
) -> auth_service.Principal:
    token = _bearer(request)
    try:
        principal = auth_service.authenticate(token, cfg)
    except auth_service.AuthError as e:
        if e.status == 401:
            raise HTTPException(
                401, e.detail, headers={"WWW-Authenticate": "Bearer"}
            ) from e
        raise HTTPException(e.status, e.detail) from e
    request.state.principal = principal
    return principal


def require_roles(*roles: Role):
    """Dependency factory: 403 unless the authenticated principal holds one of
    `roles`. Authentication (401) happens first, in `get_principal`."""

    def _dep(
        principal: auth_service.Principal = Depends(get_principal),
    ) -> auth_service.Principal:
        if roles and not principal.has_any(*roles):
            raise HTTPException(
                403,
                f"requires one of roles {sorted(r.value for r in roles)}; "
                f"token has {sorted(r.value for r in principal.roles)}",
            )
        return principal

    return _dep


def _has_flagged_run(session: Session, version_id: str) -> bool:
    run = session.exec(
        select(EvaluationRun).where(
            EvaluationRun.model_version_id == version_id,
            EvaluationRun.verdict == Verdict.pending_adjudication,
        )
    ).first()
    if run is not None:
        return True
    version = session.get(ModelVersion, version_id)
    return version is not None and version.status is ModelStatus.pending_adjudication


def authorize_object_read(
    principal: auth_service.Principal, version: ModelVersion, session: Session
) -> None:
    """Authorization matrix, per-object read (security-boundary.md):

    - auditor: all
    - submitter: own registrations only (submitted_by == principal_key)
    - adjudicator: related flagged cases only
    - governance: no arbitrary model/card/history read (uses run-evidence and
      golden-set status endpoints instead)
    """
    if principal.has_any(Role.auditor):
        return
    if principal.has_any(Role.submitter) and version.submitted_by == principal.principal_key:
        return
    if principal.has_any(Role.adjudicator) and _has_flagged_run(session, version.id):
        return
    raise HTTPException(403, "not authorized to read this model (object scope)")
