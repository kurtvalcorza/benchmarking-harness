"""OIDC bearer authentication + role mapping (T018, security-boundary.md).

Authentication and authorization are separate stages. This module does the
first: it validates a token's signature and claims and returns a typed
`Principal`. Authorization (role/object checks) lives in `app/api/auth.py`.

Two modes (config.auth_mode):
- ``oidc`` (production): RS256/ES256 validated against the issuer's JWKS, with
  iss/aud/exp/nbf enforced and the algorithm allow-listed.
- ``dev`` (local only, refused in production): deterministic HS256 tokens signed
  with a local secret, minted by ``scripts/dev_token.py`` and the test suite.

The canonical identity persisted everywhere is ``principal_key = issuer|subject``
(never the bare subject, so two issuers with the same subject stay distinct).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import jwt

from app.db.enums import Role
from app.services.config import AppConfig, load_config

DEV_ISSUER = "harness-dev"
DEV_AUDIENCE = "harness-dev"

# ``roles`` claim shapes we understand: a flat list, or Keycloak's
# ``realm_access.roles``. Unknown role strings are ignored, not fatal.
_ROLE_VALUES = {r.value for r in Role}


class AuthError(Exception):
    """Raised on any authentication failure. `status` is 401 for bad tokens."""

    def __init__(self, detail: str, status: int = 401):
        super().__init__(detail)
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class Principal:
    subject: str  # raw OIDC `sub`
    issuer: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    display: str | None = None
    token_id: str | None = None

    @property
    def principal_key(self) -> str:
        return f"{self.issuer}|{self.subject}"

    def has_any(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)


def _parse_roles(payload: dict) -> frozenset[Role]:
    raw: list[str] = []
    claim = payload.get("roles")
    if isinstance(claim, list):
        raw.extend(str(r) for r in claim)
    elif isinstance(claim, str):
        raw.extend(claim.split())
    realm = payload.get("realm_access")
    if isinstance(realm, dict) and isinstance(realm.get("roles"), list):
        raw.extend(str(r) for r in realm["roles"])
    return frozenset(Role(r) for r in raw if r in _ROLE_VALUES)


def _principal_from_payload(payload: dict, issuer: str) -> Principal:
    subject = payload.get("sub")
    if not subject or not isinstance(subject, str):
        raise AuthError("token has no stable subject")
    return Principal(
        subject=subject,
        issuer=issuer,
        roles=_parse_roles(payload),
        display=payload.get("email") or payload.get("name"),
        token_id=payload.get("jti"),
    )


# --------------------------------------------------------------------------- #
# Dev mode                                                                     #
# --------------------------------------------------------------------------- #


def mint_dev_token(
    subject: str,
    roles: list[str],
    *,
    cfg: AppConfig | None = None,
    expires_in: int = 3600,
    issued_now: float | None = None,
) -> str:
    """Mint a locally-signed HS256 dev token. Single source of truth shared by
    the dev-token CLI and the test suite so both agree with `authenticate`."""
    cfg = cfg or load_config()
    now = int(issued_now if issued_now is not None else time.time())
    payload = {
        "iss": DEV_ISSUER,
        "aud": DEV_AUDIENCE,
        "sub": subject,
        "roles": list(roles),
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, cfg.dev_signing_secret, algorithm=cfg.dev_token_algorithm)


def _authenticate_dev(token: str, cfg: AppConfig) -> Principal:
    try:
        payload = jwt.decode(
            token,
            cfg.dev_signing_secret,
            algorithms=[cfg.dev_token_algorithm],
            audience=DEV_AUDIENCE,
            issuer=DEV_ISSUER,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid dev token: {e}") from e
    return _principal_from_payload(payload, DEV_ISSUER)


# --------------------------------------------------------------------------- #
# OIDC mode                                                                    #
# --------------------------------------------------------------------------- #

_jwk_clients: dict[str, jwt.PyJWKClient] = {}


def _jwks_uri(cfg: AppConfig) -> str:
    if cfg.oidc_jwks_url:
        return cfg.oidc_jwks_url
    # OIDC discovery: fetch the issuer's well-known config for its jwks_uri.
    import httpx

    disc = cfg.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    resp = httpx.get(disc, timeout=5.0)
    resp.raise_for_status()
    uri = resp.json().get("jwks_uri")
    if not uri:
        raise AuthError("issuer discovery document has no jwks_uri")
    return uri


def _jwk_client(cfg: AppConfig) -> jwt.PyJWKClient:
    uri = _jwks_uri(cfg)
    client = _jwk_clients.get(uri)
    if client is None:
        client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=300)
        _jwk_clients[uri] = client
    return client


def reset_jwks_cache() -> None:
    _jwk_clients.clear()


def _authenticate_oidc(token: str, cfg: AppConfig) -> Principal:
    algorithms = [a for a in cfg.oidc_algorithms if a.lower() != "none"]
    if not algorithms:
        raise AuthError("no non-'none' JWT algorithm is configured", status=500)
    try:
        signing_key = _jwk_client(cfg).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=algorithms,
            audience=cfg.oidc_audience,
            issuer=cfg.oidc_issuer,
            # security-boundary.md: production tokens must carry a valid exp AND
            # nbf (the not-before time-window bound), plus a stable subject.
            options={"require": ["exp", "nbf", "iat", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid token: {e}") from e
    except Exception as e:  # JWKS fetch / network failure → treat as unauthenticated
        raise AuthError(f"token key resolution failed: {e}") from e
    return _principal_from_payload(payload, cfg.oidc_issuer)


def authenticate(token: str, cfg: AppConfig | None = None) -> Principal:
    """Validate a bearer token and return the authenticated principal.

    Raises AuthError (401) on any signature/claim failure. Does NOT check roles
    — that is authorization, done separately so a valid-but-under-privileged
    token yields 403, not 401 (security-boundary.md Failure semantics).
    """
    cfg = cfg or load_config()
    if not token:
        raise AuthError("missing bearer token")
    if cfg.dev_auth_enabled:
        return _authenticate_dev(token, cfg)
    if cfg.auth_mode == "dev":
        # dev mode requested but environment is production → never accept
        raise AuthError("dev auth is disabled in production", status=500)
    return _authenticate_oidc(token, cfg)
