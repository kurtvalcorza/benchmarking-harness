# Feature Specification: Model Benchmarking Harness (POC)

**Feature Branch**: `001-model-benchmarking-harness`

**Created**: 2026-07-10

**Status**: Draft

**Input**: User description: "Standardized AI Model Benchmarking Protocol — POC evaluation harness that gates computer-vision models before they enter an AI model repository, via a three-tier evaluation stack with a mandatory human adjudication gate and auto-generated Model Cards. Licensing-clean (code-only, no restricted data)."

**Constitution**: governed by v1.0.0 (`.specify/memory/constitution.md`). Principles I (Human-in-the-Loop) and II (Licensing-Clean) are non-negotiable.

## Clarifications

### Session 2026-07-10

- Q: Which model class is the POC pilot built around? → A: **All classes supported** via the model-class-keyed benchmark registry (design target, Constitution III / FR-006); the POC **demonstrates end-to-end on object detection + image classification first** (permissive stand-in data readily available), with segmentation/pose/lane/face registered and exercisable as stand-in datasets are added — no harness change (FR-020).
- Q: What form does a submitted model take, and how does the harness run it? → A: A **serialized weights file + declared framework/architecture** (e.g. `.pt` / `.onnx`), executed via a per-framework inference adapter inside the no-egress sandbox.
- Q: Primary interaction surface for the POC? → A: A **web application** — a submitter surface plus a **single-reviewer adjudication UI** (multi-member committee workflow stays out of scope).
- Q: Golden Test Set for the POC — real curated or stand-in? → A: A **permissively licensed public stand-in** (e.g. an Open Images subset), keeping the repo license-clean and unblocking the POC from real-dataset sourcing/legal clearance; the real curated local-context set is future work.

### Session 2026-07-10 (analyze remediation)

- Q: Where are safety-critical classes designated? → A: **In the Golden Test Set manifest** — a `safety_critical` class list plus per-class recall floors; travels with the data and is domain-appropriate (FR-026).
- Q: What routes a run to the human adjudication gate? → A: A run is **flagged → `pending_adjudication`** when (a) any safety-critical class's recall (clean or any perturbed condition) is below its floor, (b) a threshold is unratified, or (c) declared provenance is incomplete. Other below-threshold results **auto-reject** (`fail`) (FR-012).
- Q: Robustness (data-drift / shortcut) in the POC? → A: **De-scoped** — POC Tier 3 covers interpretability (visual grounding) + resource profile only (FR-022, Out of Scope).
- Note (D1): tiers execute **inside** the no-egress sandbox; a run-time no-network assertion is added (Constitution IV).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automated three-tier evaluation (Priority: P1)

A team submits a computer-vision model. The system automatically evaluates it across three tiers — general capability, local-context stress, and operational safety — and returns a clear verdict (pass / fail / pending-adjudication) with a per-tier reason.

**Why this priority**: This is the core of the harness — without automated multi-tier evaluation there is no gate. It alone delivers a usable MVP: a model in, an evidenced verdict out.

**Independent Test**: Submit one model of a supported class; confirm an evaluation runs end-to-end without manual steps and produces a stored result for each tier plus an overall verdict.

**Acceptance Scenarios**:

1. **Given** a submitted model of a supported class, **When** it is uploaded, **Then** an evaluation starts automatically and stores a result for each of the three tiers.
2. **Given** a model below the Tier 1 threshold, **When** Tier 1 completes, **Then** the model does not proceed to Tier 2/3, its verdict is `fail`, and the failing metric is named and recorded.
3. **Given** a completed evaluation, **When** the submitter views it, **Then** each tier's verdict and the reason for any failure are visible.

---

### User Story 2 - Human adjudication of safety-critical failures (Priority: P1)

A technical adjudicator reviews flagged failures with their evidence and records an approve/reject decision that becomes part of the model's permanent record.

**Why this priority**: Constitution Principle I (non-negotiable). No model may be approved automatically; the human gate is the accountability backstop and must exist for the harness to be trustworthy.

**Independent Test**: Force a flagged/safety-critical failure; confirm the model sits at `pending-adjudication`, evidence is attached, and a recorded human decision is required to move it.

**Acceptance Scenarios**:

1. **Given** an evaluation with a flagged or safety-critical failure, **When** it finishes, **Then** the model status is `pending-adjudication`, never `approved`.
2. **Given** a flagged case, **When** the adjudicator opens it, **Then** the evidence behind the flag is attached and reviewable without re-running anything.
3. **Given** the adjudicator's decision, **When** it is recorded, **Then** decision, rationale, reviewer identity, and timestamp are stored permanently on the model.

---

### User Story 3 - Model Card on every approval (Priority: P1)

Every approved model carries a generated Model Card listing its scores, known limitations, and declared training provenance, so an owner can answer an audit from the card alone.

**Why this priority**: The Model Card is the transparency/auditability artifact; without it "approved" is not defensible. Constitution Principle V.

**Independent Test**: Take one model through to completion; confirm a card is generated that preserves human-authored sections and adds populated Benchmark Results, Provenance, and (if applicable) Adjudication blocks, with missing fields marked `to be confirmed`.

**Acceptance Scenarios**:

1. **Given** a completed evaluation, **When** the Model Card is generated, **Then** it preserves the model's human-authored sections and adds populated Benchmark Results, Provenance, and (if applicable) Adjudication blocks.
2. **Given** a model with a missing or unverifiable field, **When** the card is generated, **Then** that field is marked `to be confirmed` — never blank and never invented.

---

### User Story 4 - Local-context stress testing with per-class results (Priority: P1)

Tier 2 tests the model on a versioned Golden Test Set (a permissive public stand-in in the POC; a curated local-context set in production) and under adverse conditions, surfacing per-class results.

**Why this priority**: The domain gate is the whole reason the harness beats public leaderboards; per-class surfacing (Constitution III) is what stops a model passing while hiding minority-class collapse.

**Independent Test**: Run Tier 2 for one pilot model; confirm clean and per-condition scores are stored separately, a degradation curve is produced, and per-class results for safety-critical classes are shown.

**Acceptance Scenarios**:

1. **Given** a versioned Golden Test Set, **When** Tier 2 runs, **Then** the model is scored on clean data and on each adverse condition (rain, low-light, fog) separately, and the worst-case drop from clean is reported.
2. **Given** Tier 2 results, **When** reviewed, **Then** per-class results for safety-critical classes are shown, not only an aggregate score.
3. **Given** a Tier 2 result, **When** stored, **Then** it records the Golden Test Set identifier, version, and content checksum.

---

### User Story 5 - Performance history across resubmissions (Priority: P2)

A submitter who resubmits a corrected model sees its full evaluation history across versions.

**Why this priority**: Important for verifying that fixes actually improved the failing dimension, but the gate functions without it for a first MVP.

**Independent Test**: Submit two versions of a model; confirm both runs and verdicts are returned in order and neither is overwritten.

**Acceptance Scenarios**:

1. **Given** a model with multiple submissions, **When** its history is queried, **Then** all prior runs and verdicts are returned in order, append-only.

---

### User Story 6 - Add a domain without changing the harness (Priority: P2)

A governance owner adds a new Golden Test Set (a new domain) without changing harness code.

**Why this priority**: Enables scaling past the pilot domain; not required for the single-domain MVP.

**Independent Test**: Register a new manifest-conforming Golden Test Set; confirm a compatible model can be evaluated against it with no code change.

**Acceptance Scenarios**:

1. **Given** a new Golden Test Set conforming to the defined manifest, **When** it is registered, **Then** the harness evaluates a compatible model against it with no code change.

---

### Edge Cases

- **Tier 1 failure** halts progression; Tier 2/3 skipped; scores still recorded.
- **Incomplete provenance** does not silently pass — the card marks it `to be confirmed`, and it is legitimate grounds to hold approval.
- **Golden Test Set updated** → models previously evaluated against the prior version are flagged for re-evaluation.
- **Unratified threshold** → the affected verdict is `pending_adjudication`, not `pass`.
- **Safety-critical class below its recall floor** (clean or any perturbed condition) → the run is **flagged** (`pending_adjudication`), not auto-rejected — a human decides (Constitution I).
- **Model runnable only on datacenter hardware** → resource profile records it as not edge-deployable (informational, not an automatic fail).
- **Infrastructure failure vs model failure** must be distinguishable — an infra failure is not recorded as a model `fail`.
- **Restricted dataset** is never bundled in the repo; only owned/permissive data is committed (Constitution II).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a submitted model and version, assign a unique identifier, and set initial status `pending`.
- **FR-002**: System MUST capture submitter-declared training-source provenance at submission and flag any missing required field.
- **FR-003**: System MUST automatically initiate an evaluation when a model version is uploaded, with no manual trigger.
- **FR-004**: System MUST flag previously evaluated models for re-evaluation when a Golden Test Set they were evaluated against is updated.
- **FR-005**: System MUST evaluate a model across three tiers in order (capability → domain stress → operational/safety) and record structured per-test results for each.
- **FR-006**: System MUST select the Tier 1 capability benchmark from the model's declared class via a **model-class → benchmark registry** covering all supported classes (e.g. object detection → COCO/LVIS; classification → ImageNet; segmentation → Cityscapes; pose → COCO Keypoints; lane → CULane; face → WFLW). Vision-language / document benchmarks (MMMU, MathVista, DocVQA) are out of scope for the POC.
- **FR-007**: System MUST NOT advance a model past a tier whose result is below the tier's threshold; failing scores MUST still be recorded.
- **FR-008**: Tier 2 MUST run the model against a versioned Golden Test Set and under adverse-condition perturbations (rain, low-light, fog), scoring clean and each condition **separately** and reporting the worst-case drop from clean.
- **FR-009**: Tier 2 MUST surface per-class results for the **safety-critical classes declared in the Golden Test Set manifest** (FR-026), not aggregate scores only.
- **FR-010**: System MUST execute each evaluation in isolation such that a run cannot access external networks or another run's data.
- **FR-011**: System MUST assign each evaluation a verdict of `pass`, `fail`, or `pending-adjudication` against defined thresholds.
- **FR-012**: System MUST route a run to the human adjudication gate (`pending_adjudication`) when **any** of: (a) a **safety-critical class's recall** (on clean or any perturbed condition) is below its configured floor; (b) a **threshold is unratified**; (c) **declared provenance is incomplete**. A flagged model MUST NOT reach `approved` without a recorded human decision. Below-threshold results that are none of (a)–(c) **auto-reject** (`fail`).
- **FR-013**: System MUST record each adjudication decision with rationale, reviewer identity, and timestamp, permanently attached to the model.
- **FR-014**: On completion the system MUST generate a Model Card that preserves the model's human-owned sections and adds machine-generated Benchmark Results, Provenance, and Adjudication blocks.
- **FR-015**: Missing or unverifiable Model Card fields MUST be marked `to be confirmed` — never blank and never fabricated.
- **FR-016**: System MUST retain every run (pass or fail, across resubmissions) as an append-only performance history queryable per model.
- **FR-017**: System MUST maintain an append-only audit log of access events, dataset checksums, and lifecycle events.
- **FR-018**: Every Tier 2 result MUST record the Golden Test Set identifier, version, and content checksum (contamination audit trail).
- **FR-019**: The repository MUST NOT redistribute restricted datasets; committed sample/demo data MUST be owned or permissively licensed; adverse-condition perturbations MUST be produced by applying permissively licensed transforms to owned data.
- **FR-020**: The harness MUST accept a new Golden Test Set conforming to a defined manifest without code changes (domain-agnostic).
- **FR-021**: System MUST expose each model's status (`pending` / `pending-adjudication` / `approved` / `rejected`) and its current Model Card.
- **FR-022**: Tier 3 MUST record interpretability (visual grounding) outcomes and a resource-efficiency profile (latency, throughput, parameters/memory) including an edge profile. *(Robustness / data-drift / shortcut testing is out of scope for the POC — see Out of Scope.)*
- **FR-023**: System MUST accept a model as a serialized weights file with a declared framework/architecture and MUST execute it through a per-framework inference adapter within the isolated, no-egress run environment.
- **FR-024**: The POC MUST provide a web application offering (a) a **submitter surface** to upload a model, declare its class and provenance, and view its status, results, and Model Card; and (b) a **single-reviewer adjudication surface** to review flagged cases with attached evidence and record a decision + rationale.
- **FR-025**: The system MUST demonstrate end-to-end evaluation for at least the **object-detection** and **image-classification** classes in the POC, and MUST allow additional registered classes to be exercised by supplying a conforming Golden Test Set, without harness code changes.
- **FR-026**: A Golden Test Set manifest MUST declare its **safety-critical classes** and a **per-class recall floor** for each. These declarations drive the Tier 2 per-class check (FR-009) and the adjudication flag rule (FR-012). Floors are provisional/configurable in the POC (ratified by governance later).

### Key Entities

- **Model**: a submitted model, provided as a serialized weights file with a declared framework/architecture; has a class (detection, segmentation, classification, pose, lane, face) that determines its Tier 1 benchmark via the registry.
- **Model Version**: a specific submission; carries status and submission time.
- **Evaluation Run**: one execution of the three-tier suite against a Model Version; append-only.
- **Tier Result**: per-tier outcome; Tier 2 holds one record per adverse condition.
- **Golden Test Set**: a versioned, never-public, checksummed, owned domain dataset with a defined manifest that declares its safety-critical classes and per-class recall floors (FR-026).
- **Model Card**: a two-author document — human-owned qualitative sections + machine-generated result/provenance/adjudication blocks.
- **Adjudication Record**: a permanent human decision (trigger, evidence, reviewer, decision, rationale, timestamp).
- **Audit Event**: an append-only record of access, checksums, and lifecycle changes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of models admitted to the repository during the POC have a completed three-tier evaluation and a generated Model Card; 0 are admitted without one.
- **SC-002**: 0 flagged or safety-critical models reach `approved` without a recorded human decision.
- **SC-003**: In ≥95% of evaluations, a submitter reaches a verdict from upload with no manual pipeline step.
- **SC-004**: Re-running the same model against the same Golden Test Set reproduces its verdict (scores within a defined tolerance) in ≥99% of repeated runs.
- **SC-005**: Every approved model's full evaluation lineage (all runs, tiers, adjudications) is reconstructable from stored records.
- **SC-006**: For at least one pilot model, Tier 2 produces per-class recall for safety-critical classes AND a clean-vs-perturbed degradation curve across ≥3 conditions.
- **SC-007**: The repository contains zero restricted datasets, and 100% of committed sample data is owned or permissively licensed.
- **SC-008**: A new Golden Test Set can be added and a compatible model evaluated against it with no change to harness code.
- **SC-009**: A reviewer can determine why any model failed (the responsible tier and metric) directly from the stored result, without re-running the evaluation.

## Assumptions

- **Model classes: all supported via the class-keyed benchmark registry** (Constitution III, FR-006). The POC demonstrates end-to-end on **object detection + image classification** first (permissive stand-in data readily available); segmentation, pose, lane, and face are registered and become exercisable as conforming stand-in datasets are added, with no harness change (FR-020, FR-025). *(Resolves OQ-1.)*
- **Golden Test Set (POC) = a permissively licensed public stand-in** (e.g. an Open Images subset). Keeps the repo license-clean and unblocks the POC from real-dataset sourcing and legal clearance; a real curated local-context set is future work. *(Reframes OQ-6/OQ-7 — not blocking for the POC.)*
- **Interface = a web application** with a submitter surface and a single-reviewer adjudication UI. *(Resolves the interaction-surface question.)*
- **Model artifact = serialized weights + declared framework** (e.g. `.pt` / `.onnx`), run via a per-framework inference adapter in the sandbox. *(Resolves the artifact-form question.)*
- **Model class is declared at submission** so the correct Tier 1 benchmark is selected.
- **Thresholds are provisional/configurable** for the POC, ratified by governance later. *(OQ-3.)*
- **A single designated reviewer** performs adjudication during the POC; a multi-member committee workflow is out of scope. *(OQ-2.)*
- **A single controlled execution environment** is assumed for the POC; final hosting is deferred. *(OQ-5.)*

## Out of Scope (POC)

- Vision-language / document-understanding models and their benchmarks (MMMU, MathVista, DocVQA) — documented future model class.
- Production model-serving / inference hosting.
- Robustness / data-drift / shortcut-learning testing (Tier 3) — deferred; POC Tier 3 covers interpretability (visual grounding) + resource profiling only.
- Multiple curated domain Golden Test Sets (the POC uses permissive public stand-in data for the demonstrated classes).
- A multi-member committee adjudication workflow (the POC provides a single-reviewer adjudication UI).
- Any fully automated approval path — human-in-the-loop is mandatory (Constitution I).
- A public leaderboard or model ranking; model training or fine-tuning.
