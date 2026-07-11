"""T016: JWT validation — issuer/audience/algorithm/time/subject.

Dev mode signs HS256 tokens locally; these tests exercise the claim checks that
`authenticate` enforces before it ever maps roles.
"""

import time

import jwt
import pytest

from app.services.auth import (
    DEV_AUDIENCE,
    DEV_ISSUER,
    AuthError,
    Principal,
    authenticate,
    mint_dev_token,
)
from app.services.config import load_config


@pytest.fixture()
def cfg(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("HARNESS_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HARNESS_AUTH_MODE", "dev")
    return load_config()


def test_valid_token_authenticates_with_roles(cfg):
    token = mint_dev_token("alice", ["submitter", "auditor"], cfg=cfg)
    p = authenticate(token, cfg)
    assert isinstance(p, Principal)
    assert p.subject == "alice"
    assert p.principal_key == f"{DEV_ISSUER}|alice"
    assert {r.value for r in p.roles} == {"submitter", "auditor"}


def test_expired_token_rejected(cfg):
    token = mint_dev_token("bob", ["submitter"], cfg=cfg, expires_in=-10)
    with pytest.raises(AuthError):
        authenticate(token, cfg)


def test_wrong_issuer_rejected(cfg):
    now = int(time.time())
    token = jwt.encode(
        {"iss": "someone-else", "aud": DEV_AUDIENCE, "sub": "x", "exp": now + 60},
        cfg.dev_signing_secret,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        authenticate(token, cfg)


def test_wrong_audience_rejected(cfg):
    now = int(time.time())
    token = jwt.encode(
        {"iss": DEV_ISSUER, "aud": "other-api", "sub": "x", "exp": now + 60},
        cfg.dev_signing_secret,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        authenticate(token, cfg)


def test_wrong_signature_rejected(cfg):
    now = int(time.time())
    token = jwt.encode(
        {"iss": DEV_ISSUER, "aud": DEV_AUDIENCE, "sub": "x", "exp": now + 60},
        "a-different-secret-that-is-also-long-enough",
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        authenticate(token, cfg)


def test_missing_subject_rejected(cfg):
    now = int(time.time())
    token = jwt.encode(
        {"iss": DEV_ISSUER, "aud": DEV_AUDIENCE, "exp": now + 60},
        cfg.dev_signing_secret,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        authenticate(token, cfg)


def test_empty_token_rejected(cfg):
    with pytest.raises(AuthError):
        authenticate("", cfg)


def test_unknown_role_strings_are_ignored_not_fatal(cfg):
    token = mint_dev_token("carol", ["submitter", "root", "wheel"], cfg=cfg)
    p = authenticate(token, cfg)
    assert {r.value for r in p.roles} == {"submitter"}
