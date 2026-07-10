"""Append-only audit logging helper (T016, FR-017)."""

from sqlmodel import Session

from app.db.models import AuditEvent


def record(
    session: Session,
    *,
    actor: str,
    action: str,
    target_ref: str,
    checksum: str | None = None,
) -> AuditEvent:
    ev = AuditEvent(actor=actor, action=action, target_ref=target_ref, checksum=checksum)
    session.add(ev)
    return ev
