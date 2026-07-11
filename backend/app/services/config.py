"""Threshold + typed application configuration (T003/T010).

Thresholds live in thresholds.yaml, keyed by model class and tier. A threshold
entry carries `ratified: true|false`; an unset or unratified threshold forces
`pending_adjudication` (spec edge case, FR-012b) — never a silent pass.

`AppConfig` (T003) is the single typed view of the process environment
(environment, auth, upload, DB, queue, runner, grounding). It fails closed
(T004): an unsafe production combination raises `ConfigError` at load rather
than degrading silently.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.db.enums import ModelClass, Tier

DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parents[2] / "thresholds.yaml"

# 2 GiB default upload ceiling (plan.md constraint); overridable per environment.
DEFAULT_MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_GROUNDING_MIN_SAMPLES = 20


@dataclass(frozen=True)
class Threshold:
    metric: str
    minimum: float
    ratified: bool


def thresholds_path() -> Path:
    return Path(os.environ.get("HARNESS_THRESHOLDS", DEFAULT_THRESHOLDS_PATH))


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def get_threshold(model_class: ModelClass, tier: Tier) -> Threshold | None:
    """Return the configured threshold, or None when unset (→ pending_adjudication)."""
    raw = _load(str(thresholds_path())).get(model_class.value, {}).get(tier.value)
    if not raw or "metric" not in raw or "minimum" not in raw:
        return None
    return Threshold(
        metric=raw["metric"],
        minimum=float(raw["minimum"]),
        ratified=bool(raw.get("ratified", False)),
    )


def clear_cache() -> None:
    _load.cache_clear()


# --------------------------------------------------------------------------- #
# Typed application configuration (T003)                                       #
# --------------------------------------------------------------------------- #


class ConfigError(RuntimeError):
    """Raised when the environment describes an unsafe/incoherent configuration."""


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    return v if v not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from e


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class AppConfig:
    environment: str  # "development" | "production"
    auth_mode: str  # "oidc" | "dev"
    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_algorithms: tuple[str, ...]
    oidc_jwks_url: str | None
    dev_signing_secret: str
    dev_token_algorithm: str
    max_upload_bytes: int
    database_url: str
    redis_url: str
    eval_mode: str  # "rq" | "inline"
    sandbox_mode: str  # "docker" | "subprocess"
    runner_url: str | None
    artifacts_root: Path
    data_roots: tuple[Path, ...]
    results_root: Path
    runner_work_root: Path
    grounding_min_samples: int
    grounding_methods: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def dev_auth_enabled(self) -> bool:
        return self.auth_mode == "dev" and not self.is_production


def _repo_root() -> Path:
    # config.py lives at backend/app/services/, so the repository root — where
    # data/ and samples/ live — is four levels up.
    return Path(__file__).resolve().parents[3]


def load_config() -> "AppConfig":
    """Build the typed config from the environment, failing closed (T004).

    Read fresh each call so tests can monkeypatch the environment without a
    stale cache. Callers that need a hot path may cache the result themselves.
    """
    repo = _repo_root()
    environment = (_env("HARNESS_ENV", "development") or "development").lower()
    if environment not in ("development", "production"):
        raise ConfigError(f"HARNESS_ENV must be development|production, got {environment!r}")

    # Default auth posture depends on environment: production defaults to real
    # OIDC, development to the local dev-signing helper. Never let production
    # fall back to dev signing.
    default_auth = "oidc" if environment == "production" else "dev"
    auth_mode = (_env("HARNESS_AUTH_MODE", default_auth) or default_auth).lower()
    if auth_mode not in ("oidc", "dev"):
        raise ConfigError(f"HARNESS_AUTH_MODE must be oidc|dev, got {auth_mode!r}")

    database_url = _env("HARNESS_DATABASE_URL", "sqlite:///harness.db") or "sqlite:///harness.db"

    data_dir = _env("HARNESS_DATA_DIR")
    data_roots = tuple(
        Path(p) for p in _env_tuple(
            "HARNESS_DATA_ROOTS",
            (str(Path(data_dir)) if data_dir else str(repo / "data"), str(repo / "samples")),
        )
    )

    cfg = AppConfig(
        environment=environment,
        auth_mode=auth_mode,
        oidc_issuer=_env("HARNESS_OIDC_ISSUER"),
        oidc_audience=_env("HARNESS_OIDC_AUDIENCE"),
        oidc_algorithms=_env_tuple("HARNESS_OIDC_ALGORITHMS", ("RS256",)),
        oidc_jwks_url=_env("HARNESS_OIDC_JWKS_URL"),
        dev_signing_secret=_env("HARNESS_DEV_SIGNING_SECRET", "harness-dev-insecure-secret-change-me-32b")
        or "harness-dev-insecure-secret-change-me-32b",
        dev_token_algorithm=_env("HARNESS_DEV_TOKEN_ALG", "HS256") or "HS256",
        max_upload_bytes=_env_int("HARNESS_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
        database_url=database_url,
        redis_url=_env("HARNESS_REDIS_URL", "redis://localhost:6379/0")
        or "redis://localhost:6379/0",
        eval_mode=(_env("HARNESS_EVAL_MODE", "rq") or "rq").lower(),
        sandbox_mode=(_env("HARNESS_SANDBOX_MODE", "docker") or "docker").lower(),
        runner_url=_env("HARNESS_RUNNER_URL"),
        artifacts_root=Path(_env("HARNESS_ARTIFACTS_DIR", str(repo / "data" / "artifacts"))),
        data_roots=data_roots,
        results_root=Path(_env("HARNESS_RESULTS_DIR", str(repo / "data" / "results"))),
        runner_work_root=Path(_env("HARNESS_RUNNER_WORK_DIR", str(repo / "data" / "runner"))),
        grounding_min_samples=_env_int(
            "HARNESS_GROUNDING_MIN_SAMPLES", DEFAULT_GROUNDING_MIN_SAMPLES
        ),
        grounding_methods=_env_tuple(
            "HARNESS_GROUNDING_METHODS", ("pointing_game", "energy_inside_region")
        ),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: AppConfig) -> None:
    if cfg.max_upload_bytes <= 0:
        raise ConfigError("HARNESS_MAX_UPLOAD_BYTES must be positive")
    if cfg.grounding_min_samples <= 0:
        raise ConfigError("HARNESS_GROUNDING_MIN_SAMPLES must be positive")

    if not cfg.is_production:
        return

    # ---- production fail-closed rules (T004) ----
    if cfg.auth_mode != "oidc":
        raise ConfigError(
            "production requires HARNESS_AUTH_MODE=oidc; dev-signed tokens are refused "
            "(security-boundary.md)"
        )
    if not cfg.oidc_issuer or not cfg.oidc_audience:
        raise ConfigError(
            "production requires HARNESS_OIDC_ISSUER and HARNESS_OIDC_AUDIENCE"
        )
    if "none" in {a.lower() for a in cfg.oidc_algorithms}:
        raise ConfigError("the 'none' JWT algorithm is never allowed")
    if cfg.database_url.startswith("sqlite"):
        raise ConfigError(
            "production must use a PostgreSQL database (migrations replace create_all); "
            "sqlite is for tests/offline demo only"
        )
    if cfg.eval_mode not in ("rq", "inline"):
        raise ConfigError(f"HARNESS_EVAL_MODE must be rq|inline, got {cfg.eval_mode!r}")
    if cfg.sandbox_mode != "docker":
        raise ConfigError(
            "production must run models in the hardened docker sandbox, not the subprocess "
            "fallback (security-boundary.md)"
        )


def resolves_beneath(candidate: Path, roots: tuple[Path, ...]) -> bool:
    """True when `candidate` resolves (after symlinks) beneath any allowlisted root.

    Shared containment check used by golden-set registration (T020a) and the
    runner request validation (T072).
    """
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False
