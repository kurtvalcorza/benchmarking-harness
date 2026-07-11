"""Append-only audit logging helper (FR-017; feature 002 identity, T021).

Every privileged change records the authenticated principal key, issuer, action,
target, request id, and outcome. Tokens, authorization headers, raw model bytes,
and Golden Test Set contents are forbidden here (security-boundary.md) — callers
pass only sanitized metadata.
"""

from sqlmodel import Session

from app.db.models import AuditEvent


def record(
    session: Session,
    *,
    actor: str,
    action: str,
    target_ref: str,
    checksum: str | None = None,
    request_id: str | None = None,
    principal_issuer: str | None = None,
    outcome: str | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        actor=actor,
        action=action,
        target_ref=target_ref,
        checksum=checksum,
        request_id=request_id,
        principal_issuer=principal_issuer,
        outcome=outcome,
        audit_metadata=metadata,
    )
    session.add(ev)
    return ev
