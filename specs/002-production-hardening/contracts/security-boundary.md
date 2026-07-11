# Contract: Identity, Authorization, and Sandbox Boundary

**Version**: `002.1`
**Feature**: `002-production-hardening`

## Identity contract

Production requests use `Authorization: Bearer <access-token>`. Authentication and authorization are separate stages: authentication validates the token and maps an identity; authorization then decides whether that identity may perform the requested operation.

The validator authenticates a token only when:

- its signature validates against a key from the configured OIDC issuer;
- `iss` and `aud` match configuration;
- `exp` and `nbf` are valid within configured clock skew;
- its algorithm is explicitly allowed;
- it contains a stable subject.

Recognized roles from the token are mapped onto the resulting principal, but a valid token that carries no role required for the requested operation is **authenticated** and then **denied at authorization** — `403`, not rejected as an invalid token with `401` (see Failure semantics). This keeps the role-matrix scenarios correct: e.g. a valid submitter token used on Golden Set registration authenticates, then returns `403`.

The application derives:

```text
principal_key = issuer + "|" + subject
```

Raw tokens and token payloads are not persisted. Display/email claims are non-authoritative presentation data.

## Authorization matrix

| Operation | submitter | governance | adjudicator | auditor |
|---|:---:|:---:|:---:|:---:|
| Submit model | yes | optional if multi-role | no | no |
| Read own model/card/history | yes | no | related flagged cases | all |
| Read arbitrary run evidence | no | affected registrations | related flagged cases | all |
| Register Golden Test Set | no | yes | no | no |
| Read Golden Set + its re-evaluation status | no | own registrations | no | all |
| Read adjudication queue | no | no | yes | yes (read-only) |
| Record adjudication | no | no | yes | no |
| Read security/audit metadata | no | limited to own actions | related decisions | yes |

Endpoints may require the union of roles for reads, but state-changing operations use the exact role shown. Service-layer checks prevent bypass through internal calls.

## Local development mode

- `HARNESS_AUTH_MODE=dev` may enable deterministic locally signed test tokens.
- Dev mode is rejected when `HARNESS_ENV=production`.
- Dev signing material is generated locally/ignored and never committed.
- There is no anonymous mode for state-changing endpoints; automated tests explicitly attach principals.

## Audit rules

- Successful privileged changes record principal key, issuer, action, target, request ID, outcome, and timestamp.
- Denials emit security telemetry with request ID and non-sensitive reason code.
- Tokens, authorization headers, raw model bytes, and Golden Test Set contents are forbidden in logs.

## Sandbox launch contract

Only the dedicated runner boundary may translate a validated evaluation request into container options. Callers provide model/framework/dataset identifiers, never raw mounts, images, commands, capabilities, or network modes.

Required container settings:

```yaml
network_mode: none
read_only: true
user: "65532:65532"
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
pids_limit: 256
mem_limit: configured
nano_cpus: configured
tmpfs:
  /tmp: rw,nosuid,nodev,noexec,size=256m
```

Additionally:

- apply the repository's pinned seccomp profile;
- mount code, artifact, and dataset read-only from allowlisted roots;
- mount one unique bounded output directory read-write;
- prevent access to the container-runtime socket from the model container, API, and frontend;
- force-remove the container on success, failure, or timeout;
- use a digest-pinned sandbox image built with a non-root user;
- record the effective isolation configuration and image digest in run evidence.

## Runner request validation

- Artifact path must resolve beneath the configured artifact root and match the stored ArtifactReceipt digest.
- Dataset path must resolve beneath configured data/sample roots and match the registered checksum.
- Output path must be a newly allocated directory beneath the runner work root.
- Framework/model class must be supported by the adapter registry.
- Any path translation must preserve root containment after symlink resolution.

## Failure semantics

- Invalid token: `401` with `WWW-Authenticate: Bearer`; no domain mutation.
- Insufficient role/object access: `403`; no domain mutation.
- Runner policy violation or unavailable hardening control: typed infrastructure failure; never a model `fail` and never fallback to weaker production execution.
- Subprocess fallback is limited to explicit test/demo mode and safe stub adapters; production startup rejects it.
