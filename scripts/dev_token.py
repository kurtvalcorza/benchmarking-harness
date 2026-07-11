"""Mint a local development bearer token (T022).

    python scripts/dev_token.py --subject alice --role submitter

Refuses to run unless dev auth is enabled (HARNESS_AUTH_MODE=dev and
HARNESS_ENV != production). Tokens are HS256-signed with the local dev secret and
are never valid against a production OIDC deployment. Do not commit emitted
tokens.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.auth import mint_dev_token  # noqa: E402
from app.services.config import load_config  # noqa: E402

VALID_ROLES = ("submitter", "governance", "adjudicator", "auditor")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a local dev bearer token")
    parser.add_argument("--subject", required=True, help="stable subject (OIDC sub)")
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        choices=VALID_ROLES,
        help="role to grant (repeatable)",
    )
    parser.add_argument("--expires", type=int, default=3600, help="lifetime in seconds")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.dev_auth_enabled:
        parser.error(
            "dev tokens require HARNESS_AUTH_MODE=dev and a non-production HARNESS_ENV "
            f"(env={cfg.environment}, auth_mode={cfg.auth_mode}); refusing to mint"
        )
    if not args.role:
        parser.error("grant at least one --role")

    token = mint_dev_token(args.subject, args.role, cfg=cfg, expires_in=args.expires)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
