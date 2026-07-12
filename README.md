# benchmarking-harness

A standardized, **model-class-aware** benchmarking harness that gates computer-vision models before they enter an AI model repository. Built as a proof of concept for a domain-specific evaluation pipeline — general capability, local-context stress testing, and operational-safety auditing — with a mandatory human review gate and auto-generated Model Cards.

> **Status:** POC — three specs shipped: `specs/001-model-benchmarking-harness/`
> (the full three-tier gate, all 68 tasks), `specs/002-production-hardening/`
> (COCO-reference detection metric, no-egress runner boundary, migrations,
> security gates), and `specs/003-cv-benchmarks/` (the core CV capability
> benchmarks — detection, classification, and **image segmentation → semantic
> mIoU**). Each spec's `validation.md` holds its scenario record.

## What it does

Every submitted model passes a three-tier **Evaluation Stack** before approval:

1. **Tier 1 — Capability.** The standard benchmark **for the model's class** (detection → COCO/LVIS mAP `coco_ap_50_95`, classification → ImageNet top-1, segmentation → Cityscapes-style semantic **mIoU**), against a configurable Minimum Viable Competence threshold. The benchmark is a slot keyed to model class (`backend/engine/registry/`), not a fixed list.
2. **Tier 2 — Domain stress.** The model is scored on a curated, versioned domain "Golden Test Set," then re-scored under adverse-condition perturbations (rain, low-light, fog), each condition reported separately, with the **class-appropriate per-class metric** surfaced for the manifest's safety-critical classes — recall for detection/classification, IoU for segmentation — each checked against its declared floor.
3. **Tier 3 — Operational & safety.** Interpretability (visual grounding) and resource efficiency (latency, throughput, footprint, edge profile). *(Drift/shortcut robustness probes are deferred past the POC.)*

Flagged runs — a safety-critical class under its declared floor, an unratified threshold, or incomplete provenance — route to a **mandatory human adjudication gate**; no flagged model is ever auto-approved, and every decision (reviewer, rationale, timestamp) is permanent. Every completed model carries a generated **Model Card**: human-authored sections preserved, machine blocks regenerated per run, unknown fields marked `to be confirmed` — never invented.

All model inference executes inside a **no-egress sandbox** (Docker `--network none`, read-only mounts, resource caps — with a guarded-subprocess fallback), and the run begins with a runtime assertion that the network is actually unreachable. Runs, tier results, adjudications, and audit events are **append-only**.

## Repository layout

```
backend/
  app/        FastAPI (routers, SQLModel entities, orchestrator, state machine)
  engine/     evaluation engine: registry, adapters (pytorch/onnx/stub), tiers,
              perturbations, metrics, sandbox runner, Model Card generator
  worker/     RQ worker entrypoint
  tests/      contract / integration / unit (constitution gates included)
frontend/     React + Vite + TS: Submit, Model Detail, Adjudication Queue, Review
scripts/      fetch_open_images.py · register_golden_set.py · seed_demo.py · gen_samples.py
samples/      OWNED synthetic sample data + stub demo weights (only data ever committed)
docker/       api + sandbox images · docker-compose.yml at the root
```

## Quick start (offline demo — no Docker, no downloads)

```bash
pip install -e "backend[dev]"

# terminal 1: API with inline evaluation + subprocess sandbox
HARNESS_EVAL_MODE=inline HARNESS_SANDBOX_MODE=subprocess \
  uvicorn app.main:app --app-dir backend --port 8000

# terminal 2: golden set + one healthy + one deliberately weak detector
python scripts/seed_demo.py
#   healthy-detector → approved (card generated)
#   weak-detector    → pending_adjudication (pedestrian recall below floor)

# frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Full stack (API + RQ worker + Redis + Docker sandbox): `docker compose up -d`,
then fetch real permissive data with `python scripts/fetch_open_images.py --class detection --n 200`
(`--class` also accepts `classification` and `segmentation` — the latter pulls
Open Images instance masks) and register it via
`python scripts/register_golden_set.py --class detection --data /srv/data/benchmarks/open-images-det-sample --license cc-by-4.0`
(dataset paths are the API/worker's view — `./data` is mounted at `/srv/data`, the baked-in samples at `/srv/samples`).
Evaluating real `.pt`/`.onnx` weights needs the ML extra: `pip install -e "backend[ml]"`.

### Production runner boundary (US6)

The container runtime socket is a host-escape surface. In production the API and
general worker MUST hold **no** `/var/run/docker.sock` of their own — run the
dedicated **runner** service (compose `production` profile) as the sole socket
owner and point the workers at it:

```bash
HARNESS_RUNNER_TOKEN=<secret> docker compose --profile production up -d runner
# then run api/worker with HARNESS_RUNNER_URL=http://runner:9000 (+ token) and
# WITHOUT their own docker.sock mount
```

When `HARNESS_RUNNER_URL` is set the workers delegate model execution over HTTP
(bearer-authenticated) to the runner, which re-validates every artifact/dataset/
output path against its allowlist and runs the same no-egress sandbox. The
default dev compose keeps the in-process path (worker owns the socket) for a
zero-dependency demo.

## Tests & constitution gates

```bash
cd backend && pytest            # full suite (230+ tests)
make gates                      # the three constitution gates:
#   no restricted data in the tree      (Constitution II)
#   no auto-approval path for flagged   (Constitution I)
#   sandboxed runs cannot egress        (Constitution IV / D1)
```

CI (`.github/workflows/ci.yml`) runs the gates + backend + frontend on every push.

> **Schema changes:** the POC creates tables with `create_all` and ships no
> migrations. After pulling a change that alters `backend/app/db/models.py`,
> reset local state (delete `harness.db`, or `./.state` for the compose stack) —
> an old database will fail on missing columns.

## Licensing-clean by design

This repository is **code-only**. It never redistributes third-party datasets:

- Datasets are fetched from their official sources via `scripts/` under each dataset's own terms.
- Committed sample/demo data is **owned** (procedurally generated in-repo — see `scripts/gen_samples.py` and [DATASETS.md](DATASETS.md)).
- Adverse-condition perturbations are produced by applying permissively licensed transforms to owned data — so no non-commercial dataset license is triggered by anything in this repo.

See `specs/` for the full specification and `.specify/memory/constitution.md` for the governing principles.

## License

[MIT](LICENSE) — built with AI
