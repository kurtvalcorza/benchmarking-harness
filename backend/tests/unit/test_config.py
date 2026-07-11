"""T004: typed configuration, including production fail-closed combinations.

`load_config` reads the environment fresh each call and raises `ConfigError`
for any unsafe/incoherent production posture rather than degrading silently.
"""

import pytest

from app.services.config import ConfigError, load_config, resolves_beneath


def _clear(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("HARNESS_"):
            monkeypatch.delenv(k, raising=False)


def test_development_defaults(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    assert cfg.environment == "development"
    assert cfg.auth_mode == "dev"
    assert cfg.dev_auth_enabled is True
    assert cfg.max_upload_bytes == 2 * 1024 * 1024 * 1024
    assert cfg.database_url.startswith("sqlite")


def test_production_defaults_to_oidc_and_requires_issuer(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    # no issuer/audience → fail closed
    with pytest.raises(ConfigError, match="OIDC_ISSUER"):
        load_config()


def test_production_full_oidc_ok(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    cfg = load_config()
    assert cfg.is_production
    assert cfg.auth_mode == "oidc"
    assert cfg.dev_auth_enabled is False


def test_production_refuses_dev_auth(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_AUTH_MODE", "dev")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    with pytest.raises(ConfigError, match="AUTH_MODE=oidc"):
        load_config()


def test_production_refuses_sqlite(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "sqlite:///harness.db")
    with pytest.raises(ConfigError, match="PostgreSQL"):
        load_config()


def test_production_refuses_none_algorithm(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    monkeypatch.setenv("HARNESS_OIDC_ALGORITHMS", "RS256,none")
    with pytest.raises(ConfigError, match="none"):
        load_config()


def test_production_refuses_subprocess_sandbox(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://h:h@db/h")
    monkeypatch.setenv("HARNESS_SANDBOX_MODE", "subprocess")
    with pytest.raises(ConfigError, match="hardened docker sandbox"):
        load_config()


def test_bad_upload_limit_rejected(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "0")
    with pytest.raises(ConfigError, match="MAX_UPLOAD_BYTES"):
        load_config()


def test_upload_limit_non_integer_rejected(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "big")
    with pytest.raises(ConfigError, match="integer"):
        load_config()


def test_algorithms_and_data_roots_parse(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_OIDC_ALGORITHMS", " RS256 , ES256 ")
    monkeypatch.setenv("HARNESS_DATA_ROOTS", "/a, /b ,/c")
    cfg = load_config()
    assert cfg.oidc_algorithms == ("RS256", "ES256")
    assert [str(p) for p in cfg.data_roots] == ["/a", "/b", "/c"] or len(cfg.data_roots) == 3


def test_resolves_beneath_containment(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    inside = root / "sub" / "x.json"
    inside.write_text("{}")
    outside = tmp_path / "other" / "y.json"
    outside.parent.mkdir()
    outside.write_text("{}")
    assert resolves_beneath(inside, (root,)) is True
    assert resolves_beneath(outside, (root,)) is False
