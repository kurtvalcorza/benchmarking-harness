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
from app.db.models import EvaluationRun, GoldenTestSet, ModelVersion
from app.db.repositories import get_session
from app.services import audit
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
        request: Request,
        principal: auth_service.Principal = Depends(get_principal),
        session: Session = Depends(get_session),
    ) -> auth_service.Principal:
        if roles and not principal.has_any(*roles):
            _audit_denial(session, request, principal, sorted(r.value for r in roles))
            raise HTTPException(
                403,
                f"requires one of roles {sorted(r.value for r in roles)}; "
                f"token has {sorted(r.value for r in principal.roles)}",
            )
        return principal

    return _dep


def _audit_denial(
    session: Session, request: Request, principal: auth_service.Principal, required: list[str]
) -> None:
    """FR-005: a denied privileged attempt emits sanitized security telemetry.

    Best-effort: an audit-write failure must never convert a 403 into a 500. The
    request ends at the 403, so committing this record cannot race a handler
    transaction.
    """
    try:
        audit.record(
            session,
            actor=principal.principal_key,
            action="authorization-denied",
            target_ref=f"{request.method} {request.url.path}",
            request_id=get_request_id(request),
            principal_issuer=principal.issuer,
            outcome="denied",
            metadata={"required_roles": required},
        )
        session.commit()
    except Exception:
        session.rollback()


def authorized_version_ids(
    principal: auth_service.Principal, versions: list[ModelVersion], session: Session
) -> list[str]:
    """The subset of `versions` this principal may read (history object scope,
    security-boundary.md): auditor→all, submitter→own, adjudicator→flagged."""
    if principal.has_any(Role.auditor):
        return [v.id for v in versions]
    allowed: list[str] = []
    for v in versions:
        owns = principal.has_any(Role.submitter) and v.submitted_by == principal.principal_key
        flagged = principal.has_any(Role.adjudicator) and _has_flagged_run(session, v.id)
        if owns or flagged:
            allowed.append(v.id)
    return allowed


def authorize_run_read(
    principal: auth_service.Principal, run: EvaluationRun, session: Session
) -> None:
    """Run-evidence object scope (security-boundary.md): auditor→all,
    submitter→own model version, adjudicator→related flagged case,
    governance→affected registration."""
    if principal.has_any(Role.auditor):
        return
    if principal.has_any(Role.submitter):
        version = session.get(ModelVersion, run.model_version_id)
        if version is not None and version.submitted_by == principal.principal_key:
            return
    if principal.has_any(Role.adjudicator) and _has_flagged_run(session, run.model_version_id):
        return
    if principal.has_any(Role.governance) and run.golden_set_id:
        gs = session.get(GoldenTestSet, run.golden_set_id)
        if gs is not None and gs.registered_by == principal.principal_key:
            return
    raise HTTPException(403, "not authorized to read this run's evidence (object scope)")


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
