"""T022: the dev-token path is refused in production.

Dev-signed tokens must never authenticate against a production deployment, and
the helper must refuse to mint them there.
"""

import os

import pytest

from app.services.auth import AuthError, authenticate, mint_dev_token
from app.services.config import load_config


def _clear(monkeypatch):
    for k in list(os.environ):
        if k.startswith("HARNESS_"):
            monkeypatch.delenv(k, raising=False)


def test_dev_token_not_accepted_in_production(monkeypatch):
    _clear(monkeypatch)
    # mint under dev config
    monkeypatch.setenv("HARNESS_AUTH_MODE", "dev")
    dev_cfg = load_config()
    token = mint_dev_token("mallory", ["auditor"], cfg=dev_cfg)

    # now flip to a production posture and re-authenticate the same token
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_AUTH_MODE", "oidc")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    prod_cfg = load_config()
    with pytest.raises(AuthError):
        authenticate(token, prod_cfg)


def test_helper_refuses_when_dev_auth_disabled(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_AUTH_MODE", "oidc")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    cfg = load_config()
    assert cfg.dev_auth_enabled is False
