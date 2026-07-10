# benchmarking-harness

A standardized, **model-class-aware** benchmarking harness that gates computer-vision models before they enter an AI model repository. Built as a proof of concept for a domain-specific evaluation pipeline — general capability, local-context stress testing, and operational-safety auditing — with a mandatory human review gate and auto-generated Model Cards.

> **Status:** POC / spec-driven development (see `specs/`). Greenfield.

## What it does

Every submitted model passes a three-tier **Evaluation Stack** before approval:

1. **Tier 1 — Capability.** The standard benchmark **for the model's class** (detection → COCO/LVIS mAP, classification → ImageNet top-1, etc.), against a configurable Minimum Viable Competence threshold. The benchmark is a slot keyed to model class, not a fixed list.
2. **Tier 2 — Domain stress.** The model is scored on a curated, versioned domain "Golden Test Set," then re-scored under adverse-condition perturbations (rain, low-light, fog), each condition reported separately, with per-class results surfaced.
3. **Tier 3 — Operational & safety.** Interpretability (visual grounding), robustness (drift/shortcut probes), and resource efficiency (latency, throughput, footprint, edge profile).

Flagged or safety-critical failures route to a **mandatory human adjudication gate** — no model is auto-approved. Every approved model ships a **Model Card** documenting scores, limitations, and provenance.

## Licensing-clean by design

This repository is **code-only**. It never redistributes third-party datasets:

- Datasets are fetched from their official sources via `scripts/` under each dataset's own terms.
- Committed sample/demo data is **owned or permissively licensed** only (e.g. CC BY).
- Adverse-condition perturbations are produced by applying permissively licensed transforms to owned data — so no non-commercial dataset license is triggered by anything in this repo.

See `specs/` for the full specification and `.specify/memory/constitution.md` for the governing principles.

## License

[MIT](LICENSE) — built with AI