# Threat Model — Feature 002 (Production Hardening)

**Scope**: the production-hardening surface added by Feature 002 — authenticated
API, bounded uploads, durable evaluation dispatch, the model sandbox, and the
dedicated runner boundary. Constitution invariants (human adjudication, licensing
cleanliness, no egress, append-only history, non-fabricated evidence) are the
backstop and are covered by the existing gates (`make gates`).

This is a POC threat model: it enumerates the assets, trust boundaries, the
STRIDE-style threats per boundary, and where each is mitigated in code. It is not
a formal risk assessment.

## Assets

| Asset | Why it matters |
|---|---|
| Model artifacts (uploaded weights) | Untrusted binaries; may be adversarial (pickle RCE, native egress). |
| Golden Test Sets + benchmark data | Integrity gates every verdict (FR-018 contamination guard). |
| Evaluation verdicts / Model Cards | The gate output governance relies on; must be defensible + reproducible. |
| Audit + adjudication history | Append-only accountability record (Constitution IV). |
| Access tokens | Bearer credentials; compromise grants the holder's roles. |
| The container runtime socket | Full host control if reachable from the API/UI tier. |

## Trust boundaries

1. **Client → API** — unauthenticated network to authenticated application.
2. **API/worker → model sandbox** — trusted orchestration to UNTRUSTED model code.
3. **API/worker → runner service** — application tier to the socket-owning tier.
4. **Sandbox → network** — the no-egress boundary (Constitution IV / D1).
5. **Application → database/queue** — durability + at-least-once delivery.

## Threats and mitigations (STRIDE by boundary)

### 1. Client → API
- **Spoofing / Elevation**: a caller forges identity or assumes a role.
  → OIDC bearer validation of signature/issuer/audience/exp/nbf/alg (FR-002); the
  `none` algorithm is refused; production fails closed when auth cannot be
  configured. Role + object authorization on every non-health route (FR-001/003).
  Reviewer/actor identity is derived from the token subject, never request body
  (FR-004). Tests: `test_auth_tokens.py`, `test_authorization.py`,
  `test_adjudication_identity.py`.
- **Tampering (self-asserted reviewer)**: `DecisionIn` has no reviewer field;
  extra keys are dropped.
- **Repudiation**: allowed AND denied privileged operations write sanitized audit
  telemetry with principal key + issuer + request id, never raw tokens (FR-005).
- **Denial of service (upload flood / oversized upload)**: uploads stream to a
  bounded, hashed `.part` with a configurable ceiling (default 2 GiB); oversized →
  `413`, interrupted/failed → no evaluable version, no partial artifact
  (FR-006/007). The required reverse-proxy body limit is documented (FR-008).
- **Information disclosure**: `/healthz` is public and reveals no config;
  `/readyz` requires the auditor role.

### 2. API/worker → model sandbox (UNTRUSTED code)
- **Elevation / host escape**: the model process runs non-root (UID 65532), all
  Linux capabilities dropped, `no-new-privileges`, read-only root fs, a pinned
  seccomp block-list, a bounded `noexec`/`nosuid`/`nodev` tmpfs, PID/CPU/memory
  caps, and a wall-clock timeout; only the required mounts are attached and only
  the output mount is writable (FR-024). Tests: `test_sandbox_hardening.py`
  (config-as-data) + `test_sandbox_runtime.py` (LIVE probes on a Docker host).
- **Tampering (path traversal via a crafted data_ref/artifact)**: the runner
  refuses any artifact/dataset/output path that does not resolve beneath the
  allowlisted roots, in addition to Golden Set registration containment (T020a/T072).
- **Information disclosure (egress)**: `--network none` plus an in-sandbox runtime
  assertion that aborts if the network is reachable (Constitution IV / D1). The
  subprocess fallback additionally installs a socket guard and fails closed for
  non-stub frameworks.

### 3. API/worker → runner service
- **Elevation (socket reachable from the API/UI tier)**: in production only the
  dedicated runner service holds `/var/run/docker.sock`; the API and general
  worker delegate execution over HTTP and hold no socket, so compromise of the
  API process does not grant container control (FR-025). The runner authenticates
  `/run` with a shared bearer secret and fails closed when it is unset.

### 4. Sandbox → network
- Covered under boundary 2 (no egress). The runtime assertion is the independent
  backstop even if a mount/config regression occurred.

### 5. Application → database/queue
- **Lost work (dual-write gap)**: submission and re-evaluation create a durable
  `JobIntent` in the SAME transaction as the domain change, so a committed action
  never lacks its evaluation intent (FR-016). Queue unavailability never requires
  the user to repeat a committed submission/registration (FR-018).
- **Duplicate work (at-least-once delivery)**: workers claim an intent before
  running and complete it in the run's transaction; a duplicate delivery of a
  completed intent is a no-op (FR-017). A dead worker's expired lease is reclaimed
  and its stale `evaluating` version released (no poison loop).
- **Partial/torn state**: evaluation completion and adjudication each commit
  atomically or not at all; evidence is staged, digested, atomically published,
  and compensated on rollback (FR-013/014/015).
- **Fabricated / contaminated evidence**: results carry coverage counts +
  evaluator provenance + dataset checksum (FR-012); a Golden Set whose on-disk
  content drifts from its registered checksum is refused (FR-018); grounding is
  measured or explicitly unavailable, never a confidence proxy (FR-019/020/021).

## Supply chain
- Base images and CI actions are version-pinned (SHAs); Python/Node manifests are
  locked for reproducible builds (FR-026). CI scans both dependency graphs and
  fails on high/critical advisories, with documented, time-bound exceptions only
  (FR-027, see [advisory-exception.md](advisory-exception.md)).

## Residual risks / out of scope (POC)
- No `--gpus` inside the docker sandbox (real weights run CPU there; GPU only via
  the subprocess mode on a trusted host).
- No secrets manager / token rotation automation; the dev-signing secret is for
  local development only and production requires real OIDC.
- Rate limiting / WAF at the ingress is assumed to be provided by the deployment.
- The runner shared secret is a symmetric bearer; mTLS between worker and runner
  is a hardening follow-up.
