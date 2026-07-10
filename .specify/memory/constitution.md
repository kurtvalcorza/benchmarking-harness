<!--
SYNC IMPACT REPORT
Version change: (template / unratified) → 1.0.0
Bump rationale: Initial ratification of the project constitution (MAJOR — first adoption).
Modified principles: n/a (initial)
Added principles:
  I.   Human-in-the-Loop Approval (NON-NEGOTIABLE)
  II.  Licensing-Clean, No Restricted Data (NON-NEGOTIABLE)
  III. Model-Class-Appropriate Evaluation
  IV.  Reproducibility & Contamination Resistance
  V.   Verify-First, No Fabrication
  VI.  Test-First Development
Added sections: Additional Constraints (Security & Data Handling); Development Workflow & Quality Gates; Governance
Templates requiring updates:
  ✅ .specify/templates/plan-template.md  — Constitution Check gate populated from these principles
  ✅ .specify/templates/spec-template.md  — reviewed; generic, no change needed
  ✅ .specify/templates/tasks-template.md — reviewed; generic, no change needed
Deferred TODOs: none
-->

# benchmarking-harness Constitution

A standardized, model-class-aware benchmarking harness that gates computer-vision models before they enter an AI model repository. These principles are the non-negotiable contract every spec, plan, and task must satisfy. Principles marked **(NON-NEGOTIABLE)** cannot be waived by any downstream decision, deadline, or complexity argument.

## Core Principles

### I. Human-in-the-Loop Approval (NON-NEGOTIABLE)

No model is ever approved automatically. A model flagged as a safety-critical failure, an edge case, or as otherwise below a ratified gate MUST enter a `pending-adjudication` state and be resolved by a human adjudicator before it can reach `approved`.

- Every adjudication MUST record decision, rationale, reviewer identity, and timestamp, permanently attached to the model.
- There MUST be no code path — flag, config, or override — that transitions a flagged model to `approved` without a recorded human decision.

**Rationale:** These models feed high-stakes government services. A missed emergency vehicle or misread flood-damage assessment causes real harm that surfaces only after deployment. The human gate is the accountability backstop, not an optional efficiency cost.

### II. Licensing-Clean, No Restricted Data (NON-NEGOTIABLE)

This repository is **code-only** and MUST remain publishable without redistributing third-party data.

- The repo MUST NOT commit or redistribute restricted datasets (e.g. ImageNet, Cityscapes, CULane, ACDC, AODRaw — non-commercial / no-redistribution terms).
- Datasets MUST be obtained at runtime via fetch scripts, under each dataset's own terms accepted by the user.
- Committed sample/demo data MUST be owned by the project or permissively licensed (e.g. CC BY, Open Images).
- Adverse-condition perturbations MUST be produced by applying permissively licensed transforms (e.g. Apache-licensed corruption code) to owned or permissive data — never by redistributing a restricted dataset's images.
- The design MUST NOT bake in any dependency that would break, or violate a license, if the gated platform later becomes an operational/commercial service.

**Rationale:** Most CV benchmarks are non-commercial or forbid redistribution. A public POC that bundled them would be unshippable and would create a dependency that breaks the moment the platform becomes commercial. Cleanliness is designed in from day one, not retrofitted.

### III. Model-Class-Appropriate Evaluation

The capability benchmark is a **slot keyed to the model's class**, never a fixed list.

- Tier 1 MUST select the standard benchmark for the declared model class (e.g. object detection → COCO/LVIS mAP; classification → ImageNet top-1) and MUST NOT apply a benchmark the model class cannot run.
- Vision-language / document benchmarks (MMMU, MathVista, DocVQA) are a documented **future** model class and are out of scope until such models are hosted.
- Per-class metrics for safety-critical classes are MANDATORY in domain (Tier 2) scoring. Reporting only aggregate scores that can mask minority-class collapse is FORBIDDEN.

**Rationale:** The target repositories host task-specific CV models, not VLMs — a fixed leaderboard is the wrong instrument. Aggregate-only scoring has already hidden minority-class recall collapse in prior work; surfacing per-class results is the whole point of the gate.

### IV. Reproducibility & Contamination Resistance

The same model evaluated against the same test set MUST yield the same verdict within a defined tolerance.

- Test sets MUST be version-pinned and content-checksummed; the checksum MUST be recorded on every result it produces.
- Golden Test Sets MUST NOT be public.
- Each evaluation MUST run isolated, with no network egress and no access to another run's data.
- Performance history and audit logs MUST be append-only; results are never overwritten across resubmissions.

**Rationale:** A verdict that cannot be reproduced is not evidence. Never-public sets plus no-egress isolation are the contamination defense that public leaderboards cannot provide.

### V. Verify-First, No Fabrication

Every claim the system emits MUST be backed by a measured value or explicitly marked unknown.

- Model Card fields MUST be either a measured value or the literal `to be confirmed` — never blank and never invented.
- Every result MUST carry its evidence and the dataset checksum used.
- A model MUST NOT be reported `approved` unless its full evaluation lineage (all runs, tiers, and adjudications) is reconstructable from stored records.

**Rationale:** The harness exists to replace unverified trust with traceable evidence. A fabricated or blank field silently reintroduces exactly the risk the gate removes.

### VI. Test-First Development

Development follows the spec-kit flow (constitution → specify → clarify → plan → tasks → implement). Behavior that gates a model — verdict logic, threshold checks, the adjudication transition, licensing guards — MUST have automated tests written before implementation, and those tests MUST fail before the code exists.

**Rationale:** The gate's correctness is the product. Tests-first keeps the load-bearing logic honest and prevents regressions in the rules that decide what enters national infrastructure.

## Additional Constraints — Security & Data Handling

- **Secrets** MUST NOT be committed; configuration reads secrets from ignored local files or environment.
- **PII**: domain data may contain PII (faces, plates, personal records). Retained data MUST follow data-minimization; the repo commits none of it.
- **Sandboxing**: model execution is untrusted code — it MUST run isolated with no egress (see Principle IV).
- **Audit trail**: access to Golden Test Sets and lifecycle transitions MUST be logged (append-only).

## Development Workflow & Quality Gates

- Every feature passes the **Constitution Check** in the plan before Phase 0 and again after design; violations require an entry in the plan's Complexity Tracking with justification, and **Principles I and II admit no justification — a violation blocks the work.**
- Every approved model MUST have a traceable Model Card and a reconstructable evaluation lineage (transparency/auditability gate).
- Code review MUST verify principle compliance, especially: no auto-approval path (I), no restricted data committed (II), per-class metrics present (III), and no fabricated/blank card fields (V).

## Governance

This constitution supersedes other practices in this repository. When a practice and this document conflict, this document wins.

- **Amendments** require: a written change, a version bump per the policy below, an updated Sync Impact Report, and propagation to any affected templates.
- **Versioning (semantic):** MAJOR = backward-incompatible governance/principle removal or redefinition; MINOR = a new principle/section or materially expanded guidance; PATCH = clarifications and wording.
- **Non-negotiables:** Principles I (Human-in-the-Loop Approval) and II (Licensing-Clean, No Restricted Data) cannot be waived or overridden; changing or removing either requires a MAJOR bump and an explicit, documented governance decision.
- **Compliance review:** all plans and reviews MUST verify compliance; unjustified violations block merge.

**Version**: 1.0.0 | **Ratified**: 2026-07-10 | **Last Amended**: 2026-07-10
