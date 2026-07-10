# Phase 1 — Data Model

Entities derived from the spec's Key Entities and requirements. Types are logical (implementation via SQLModel/SQLAlchemy). Append-only entities are marked 🔒 (no update/delete after insert).

## Enums

- **ModelClass**: `detection | segmentation | classification | pose | lane | face`
- **Tier**: `capability | domain_stress | operational_safety`
- **Verdict**: `pass | fail | pending_adjudication`
- **ModelStatus**: `pending | evaluating | pending_adjudication | approved | rejected`
- **Condition** (Tier 2): `clean | rain | low_light | fog`
- **Decision**: `approve | reject | request_changes`

## Entities

### Model
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | system-assigned |
| name | str | required |
| model_class | ModelClass | required; MUST have a registry entry (FR-006) |
| created_at | datetime | |

### ModelVersion
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| model_id | uuid (FK→Model) | |
| version | str | unique per model |
| artifact_ref | path | serialized weights location (gitignored store); required (FR-023) |
| framework | str | e.g. `pytorch` / `onnx`; required (FR-023) |
| declared_sources | text[] | training provenance; missing → flagged, not blank (FR-002, FR-015) |
| status | ModelStatus | starts `pending`; see state machine |
| submitted_at | datetime | |

### GoldenTestSet
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| name, domain | str | |
| model_class | ModelClass | which class it evaluates |
| version | str | immutable; change → new version, triggers re-eval (FR-004) |
| manifest_ref | path | conforms to the defined manifest (FR-020) |
| checksum | str | content hash; stamped on every result (FR-018, Constitution IV) |
| conditions | Condition[] | which perturbations are provided |
| safety_critical_classes | str[] | class labels whose per-class recall gates adjudication (FR-026) |
| recall_floors | map<str,float> | per-class recall floor for each safety-critical class (FR-026; provisional in POC) |
| license | str | MUST be owned/permissive for committed data (Constitution II) |
| is_public | bool | MUST be false (never-public invariant) |

### EvaluationRun 🔒
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| model_version_id | uuid (FK) | |
| harness_version | str | for reproducibility |
| golden_set_ref | (id, version, checksum) | recorded on the run (FR-018) |
| started_at, finished_at | datetime | |
| verdict | Verdict | computed by the scoring engine |
| infra_ok | bool | distinguishes infra failure from model `fail` (edge case) |

### TierResult 🔒
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| run_id | uuid (FK→EvaluationRun) | |
| tier | Tier | |
| condition | Condition \| null | Tier 2 has one row per condition (FR-008) |
| metrics | json | task-appropriate; includes **per-class** entries for safety-critical classes (FR-009) |
| threshold | json \| null | from config; null/unratified → forces `pending_adjudication` (edge case) |
| passed | bool \| null | null when pending |
| evidence_ref | path | artifacts backing the numbers (Constitution V) |
| dataset_checksum | str | copied from the golden set (FR-018) |

### ModelCard
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| model_version_id | uuid (FK) | one current card per version |
| human_sections | markdown | preserved across regenerations (FR-014) |
| machine_blocks | markdown | Benchmark Results + Provenance + Adjudication; regenerated per run |
| missing_fields | str[] | rendered as `to be confirmed` (FR-015, Constitution V) |
| generated_at | datetime | |

### AdjudicationRecord 🔒
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| run_id | uuid (FK) | the flagged run |
| trigger | str | safety-critical / edge / unratified-threshold / incomplete-provenance |
| evidence_ref | path | attached for review without re-running (FR-012) |
| reviewer | str | required (FR-013) |
| decision | Decision | required |
| rationale | text | required, non-empty |
| decided_at | datetime | |

### AuditEvent 🔒
| Field | Type | Rules |
|---|---|---|
| id | uuid (PK) | |
| actor | str | |
| action | str | access / checksum-verify / status-change |
| target_ref | str | |
| checksum | str \| null | |
| at | datetime | |

## Relationships

```
Model 1─* ModelVersion 1─* EvaluationRun 1─* TierResult
ModelVersion 1─1 ModelCard (current)
EvaluationRun 0..1─* AdjudicationRecord   (only when flagged)
GoldenTestSet 1─* EvaluationRun (referenced by id+version+checksum)
AuditEvent — standalone append-only log
```

`ModelVersion.status` history = the ordered set of its `EvaluationRun`s (append-only performance history, FR-016).

## State Machine — ModelVersion.status (encodes Constitution I)

```
              upload
   ┌─────────────────────► pending
   │                          │ auto-trigger (FR-003)
   │                          ▼
   │                      evaluating
   │            ┌─────────────┼───────────────┐
   │      all tiers pass   any tier fail    flagged / unratified / safety-critical
   │            ▼             ▼               ▼
   │        approved       rejected     pending_adjudication
   │                                         │
   │                        ┌────────────────┼─────────────────┐
   │                   decision=approve  decision=reject   request_changes
   │                        ▼                ▼                 ▼
   │                    approved         rejected      (back to submitter → new version)
   │
   └── golden-set update (FR-004) ─► re-flag affected versions for re-evaluation
```

**Invariant (tested):** the ONLY edge into `approved` from a flagged run passes through an `AdjudicationRecord` with `decision=approve`. There is no direct `evaluating → approved` edge when any tier produced a flag, and no API/force path that bypasses adjudication (Constitution I).

## Validation rules (cross-cutting)

- A `ModelVersion` MUST NOT reach `approved` unless every tier has a stored `TierResult` and (if flagged) an `AdjudicationRecord` — i.e. a reconstructable lineage (FR-005, Constitution V).
- `GoldenTestSet.is_public == false` and `license ∈ {owned, permissive}` for anything committed (Constitution II).
- Every `TierResult.dataset_checksum` MUST equal the referenced `GoldenTestSet.checksum` at run time (Constitution IV).
- Append-only entities reject update/delete at the repository layer.
- **Flag rule (FR-012, Constitution I):** a completed run routes to `pending_adjudication` (not `fail`) when **any** of — a safety-critical class's recall (clean or any condition) < its `recall_floors` entry; a threshold is unratified; declared provenance is incomplete. Otherwise a below-threshold result is `fail` (auto-reject) and an all-pass result is `pass`.
- **Sandbox (D1, Constitution IV):** every tier's inference executes inside the no-egress sandbox runner; the orchestrator MUST NOT run model inference in the API/worker process.
