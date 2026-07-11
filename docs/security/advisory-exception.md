# Dependency Advisory Exception Template (FR-027)

CI fails the build on **known high/critical** vulnerabilities in the Python
(`pip-audit`) and Node (`npm audit --audit-level=high`) dependency graphs. An
advisory may be temporarily excepted ONLY with a recorded, time-bound entry here.
A bare `npm audit` (any severity) is intentionally NOT the gate — the FR-027 gate
is high/critical.

## Rules

- An exception is **time-bound**: it MUST carry an expiry date. When it expires,
  CI fails again until the dependency is upgraded or the exception is renewed with
  fresh justification.
- An exception requires a **justification**: why the advisory is not exploitable
  in this system (e.g. the vulnerable code path is unreachable), or why the fix is
  blocked, plus the mitigation in place.
- An exception is **scoped** to a specific advisory id + package + version range.
- Exceptions are reviewed at every renewal; a stale, unjustified exception is a
  finding.

## How to apply an exception

Record the entry in the table below AND wire the suppression into the CI gate for
the specific advisory id (e.g. `pip-audit --ignore-vuln <ID>` /
`npm audit --audit-level=high` with the advisory acknowledged in the lockfile
review), never by lowering the global severity threshold.

## Active exceptions

| Advisory ID | Package | Affected range | Severity | Justification | Mitigation | Opened | Expires | Owner |
|---|---|---|---|---|---|---|---|---|
| _(none)_ | | | | | | | | |

## Expired / closed exceptions

| Advisory ID | Package | Closed | Resolution |
|---|---|---|---|
| _(none)_ | | | |

> As of Feature 002, `pip-audit` and `npm audit --audit-level=high` both report
> **zero** high/critical advisories (US2 promoted pycocotools to a core dep;
> T002 upgraded Vite/Vitest to supported releases), so there are no active
> exceptions.
