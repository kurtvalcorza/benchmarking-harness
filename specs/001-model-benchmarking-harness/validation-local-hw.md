# On-Hardware Validation Record — 2026-07-11

Environment: Windows 11 (native Python 3.11.9 venv) + Rancher Desktop (docker
server 29.5.3, WSL backend) + NVIDIA RTX 5070 Ti Laptop GPU (torch
2.11.0+cu128). Complements [validation.md](./validation.md), whose two recorded
deviations — no docker daemon, synthetic-only data — are both closed here.

## Suite & gates (Windows)

- **64/64 backend tests pass** (after fix F1 below; before it, 14 failed).
- The three constitution gates (no restricted data / no auto-approval /
  sandbox no-egress) pass, including the new UDP-guard test.
- Frontend `npm run build` + tests green; four UI pages exercised against the
  live stack (Submit, Model Detail, Adjudication Queue, Review — decision
  recorded through the UI, second decision correctly refused with 409).

## Full compose stack (api + RQ worker + redis)

`docker compose up -d` on Rancher Desktop; API healthy on :8000; worker
consumed RQ jobs. Quickstart Scenarios all pass live:

| Scenario | Result |
|---|---|
| **A** healthy end-to-end | ✅ `pending → evaluating → approved`, card populated, `missing_fields=[]` |
| **B** safety-critical → human | ✅ `safety_critical_recall_below_floor` (pedestrian 0.115 < 0.6), `pending_adjudication`, recorded reject → `rejected`; **second decision → 409** |
| **C** per-condition + degradation | ✅ clean/rain/low_light/fog scored separately; worst-case −0.1066 under low_light; per-class recall per condition |
| **D** reproducibility | ✅ v1 vs v3 re-run of identical weights: all verdict-driving metrics byte-identical (only Tier-3 `throughput_images_per_s` varies — timing-derived, excluded by SC-004) |
| **E** class extensibility | ✅ classifier registered + evaluated via the registry top-1 slot, `approved`, no engine change |

## Docker no-egress sandbox (D1) — validated against a live daemon

Native runner in `HARNESS_SANDBOX_MODE=docker`:

- `run_inference(...)` → `ok=True, mode=docker, egress_asserted=True`,
  predictions returned through read-only mounts + writable out dir.
- **Hostile in-container probe** using the exact `docker_container_config()`:
  outbound connect **blocked**, DNS **blocked**, code mount **read-only**,
  root fs **read-only**; `NetworkMode=none`, `ReadonlyRootfs=True`,
  `NanoCpus=2e9`, `Memory=4GiB`, `PidsLimit=256` confirmed via inspect.

## Real data + real weights (GPU)

- `fetch_open_images.py --class detection --n 200` (after fix F2): 200 real
  Open Images images / 540 boxes fetched, registered as a golden set with
  `checksum:auto` — the Constitution II **license guard rejected a free-text
  license string** and accepted `cc-by-4.0` (working as intended).
- `yolo11n.pt` (2.62 M params) submitted as `framework=pytorch`: the adapter
  ran **1116 real predictions over 200 images in 6.64 s (33.2 ms/img)** inside
  the subprocess sandbox on **torch 2.11.0+cu128** (GPU VRAM blip observed).
  Tier 1 mAP 0.0 → halt-on-fail (only 1 tier recorded) → `rejected`
  (`Verdict.fail → ModelStatus.rejected` by design). The 0.0 is finding F6.

## Fixes applied on this branch

- **F1 — `backend/engine/sandbox/job.py`**: `_install_socket_guard()`
  referenced `socket.socket.sendmsg`, which does not exist on Windows
  (Unix-only in CPython) → the guard crashed → every subprocess-sandbox run
  infra-failed → models stuck `pending` (14 test failures). Now patched only
  where the attribute exists (nothing is lost on Windows — no `sendmsg`
  means no `sendmsg` egress either).
- **F2 — `scripts/fetch_open_images.py`**: used `sample.detections`, but
  fiftyone's open-images-v7 zoo loader stores boxes in `ground_truth` → the
  real (non-`--synthetic`) fetch path crashed on the first sample. This path
  had never been executed before this record.

## Findings (not fixed here)

- **F3 — compose worker can't use the docker sandbox (missing dep):** the api
  image installs only base deps; `docker` SDK is `[ml]`-only. Auto-detection
  (`import docker`) fails → **silent fallback to subprocess mode** — verified
  live (evidence records `sandbox_mode: subprocess`). The docker-socket mount
  in `docker-compose.yml`, whose comment states the sandbox purpose, never
  engages.
- **F4 — compose docker-mode is broken even with the SDK installed:** the
  worker passes its *own container's* paths (`/srv/backend`, tempdirs) as
  bind sources; the daemon resolves them on *its* filesystem → the sibling
  sandbox container gets an empty `/srv/backend` →
  `ModuleNotFoundError: No module named 'engine'` → `infra_ok=false`
  (reproduced live). Fix direction: share code/artifacts/out via named
  volumes (volume-name keys in the SDK `volumes` dict) or daemon-visible
  host paths.
- **F5 — sandbox image can't run real models, and has no GPU:** it ships
  numpy/pillow (+ CPU torch at best) — no ultralytics/timm/onnxruntime — so
  `framework=pytorch|onnx` artifacts fail inside docker mode; and
  `docker_container_config()` requests no `device_requests` (`--gpus`), so
  docker-mode inference is CPU-only by construction. Real-weights + GPU runs
  are currently only possible via the subprocess sandbox.
- **F6 — no label-space canonicalization for real models:** a COCO-trained
  YOLO emits `person`/`car`; golden sets use `pedestrian`/`vehicle`/
  `traffic_sign` → mAP 0.0 / recall 0.0 across the board. The stub adapter
  generates predictions *from ground truth*, so no committed test can catch
  this. A per-model (or per-adapter) label-mapping layer is needed before any
  real model can pass Tier 1.
- **F7 — quickstart's compose + `seed_demo.py` combo cannot work as written**
  on any OS: the script sends a host path as `data_ref`, but the API resolves
  it server-side (inside the container) → 422. Workaround used here:
  register golden sets with the in-container path (`/srv/samples/...`).
- *(minor)* `fetch_open_images.py` detection filtering admits
  classification-only labels (`building`, `animal`) into detection
  annotations because both flows share `LABEL_CANON`.
