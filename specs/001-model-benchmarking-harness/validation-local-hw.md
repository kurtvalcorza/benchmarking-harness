# On-Hardware Validation Record — 2026-07-11

Environment: Windows 11 (native Python 3.11.9 venv) + Rancher Desktop (docker
server 29.5.3, WSL backend) + NVIDIA RTX 5070 Ti Laptop GPU (torch
2.11.0+cu128). Complements [validation.md](./validation.md), whose two recorded
deviations — no docker daemon, synthetic-only data — are both closed here.

> Baseline: the sweep below ran against `31fa4bd`. The second-round Codex
> fixes (`9bc3579..d89f69a`) landed mid-sweep and independently address
> findings F3/F4/F5/F7 below; the "Rebased head" section at the end records
> the re-validation on top of them.

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

## Findings

Found live at `31fa4bd`; F3/F4/F5/F7 were independently fixed by the
second-round Codex commits that landed mid-sweep (see "Rebased head" below
for the on-hardware re-validation of those fixes).

- **F3 — compose worker silently fell back to subprocess mode:** the api
  image installs only base deps; `docker` SDK is `[ml]`-only, so auto-detect
  (`import docker`) failed — verified live (evidence records
  `sandbox_mode: subprocess`) while the compose comment promised docker
  isolation. *Addressed at `d89f69a`*: explicit `HARNESS_SANDBOX_MODE: docker`
  fails loudly instead of downgrading, and `docker>=7.0` moved from `[ml]`
  into core deps so the worker image actually has it.
- **F4 — compose docker-mode was broken even with the SDK installed:** the
  worker passed its *own container's* paths (`/srv/backend`, tempdirs) as
  bind sources; the daemon resolves them on *its* filesystem → the sibling
  sandbox container got an empty `/srv/backend` →
  `ModuleNotFoundError: No module named 'engine'` → `infra_ok=false`
  (reproduced live). *Addressed at `d89f69a`* via `HARNESS_HOSTPATH_MAP` +
  `HARNESS_SANDBOX_WORKDIR` + host bind mounts. Both `C:/...` and `/c/...`
  forms of `${PWD}` resolve through Rancher Desktop's daemon (probed live),
  so the map works from Git Bash or PowerShell (with `PWD` provided).
- **F5 — sandbox image couldn't run real models, and still has no GPU:**
  *addressed at `d89f69a`* for CPU (torch CPU + ultralytics + timm +
  onnxruntime baked in). Still true: `docker_container_config()` requests no
  `device_requests` (`--gpus`), so docker-mode inference is CPU-only by
  construction; GPU runs require the subprocess sandbox, which since
  `d89f69a` fails closed for non-stub frameworks unless
  `HARNESS_ALLOW_UNSANDBOXED_FRAMEWORKS=1` (the GPU run above predates that
  gate and would now need the explicit opt-in).
- **F6 — no label-space canonicalization for real models (OPEN):** a
  COCO-trained YOLO emits `person`/`car`; golden sets use `pedestrian`/
  `vehicle`/`traffic_sign` → mAP 0.0 / recall 0.0 across the board. The stub
  adapter generates predictions *from ground truth*, so no committed test can
  catch this. A per-model (or per-adapter) label-mapping layer is needed
  before any real model can pass Tier 1 against a canonical golden set.
- **F7 — quickstart's compose + `seed_demo.py` combo could not work as
  written** on any OS: the script sent a host path as `data_ref`, but the API
  resolves it server-side (inside the container) → 422 (verified live).
  *Addressed at `d89f69a`*: `--data-ref` / `--data` flags + compose header
  documenting container paths.
- *(minor, OPEN)* `fetch_open_images.py` detection filtering admits
  classification-only labels (`building`, `animal`) into detection
  annotations because both flows share `LABEL_CANON`.

## Rebased head (`d89f69a` + this branch's F1/F2 fixes)

- **Backend suite: 71/71 pass** on Windows (the Codex round added 7 tests).
- **Compose docker-mode now runs real sandbox containers end-to-end.** With
  the hostpath map corrected (F8 below), a stub detector went
  `pending → evaluating → approved`, `infra_ok=true`, **6 tier results each
  in its own ephemeral `--network none` sandbox container**, and the card
  records `sandbox: docker`. This is the first time the full
  worker → host-daemon → sibling-sandbox path has run green — the F3/F4 fixes
  are confirmed on hardware.
- **F5 (CPU) confirmed loadable, F9 blocks it:** the ML-enabled sandbox image
  builds and imports ultralytics/timm/onnxruntime, but a real `yolo11n.pt`
  still can't be evaluated in docker mode — see F9.

### New findings from the rebased-head sweep

- **F8 — `${PWD}` hostpath map yields a daemon-invalid path on Docker/Rancher
  Desktop for Windows.** The daemon runs inside a WSL VM, so the worker's
  sibling-container bind sources must be `/mnt/c/...`. `${PWD}` from a Windows
  shell expands to `C:/Users/...`; docker-py in the Linux worker builds the
  bind string `C:/Users/...:/srv/backend:ro`, which the daemon rejects
  (`invalid volume specification`, reproduced live). Worse, the `/c/Users/...`
  form is accepted **but mounts empty** (silent — would resurface F4's
  `ModuleNotFoundError`); only `/mnt/c/...` mounts the real contents (all
  three forms probed live from inside the worker). Fix direction: derive the
  map from the daemon-visible mount, or document `/mnt/<drive>/...` for
  Desktop-on-Windows. Worked around here via `docker-compose.override.yml`
  (uncommitted; host-specific). *(On a native-Linux host `${PWD}` is already
  daemon-visible, so this only bites Desktop/WSL setups.)*
- **F9 — real `.pt`/`.onnx` can't load in docker mode: the artifact is
  bind-mounted at the extension-less path `/mnt/artifact`.** Ultralytics (and
  onnxruntime) dispatch on file extension, so `/mnt/artifact` is "not a
  supported model format" → `infra_ok=false` (reproduced live with
  `yolo11n.pt`). The stub adapter reads JSON regardless of extension, so no
  committed test or scenario catches this. Fix direction: mount preserving the
  suffix (e.g. `/mnt/artifact.pt`) or hand the adapter the real name. Combined
  with F5's missing `--gpus`, real models in docker mode are blocked on both
  extension and GPU; the subprocess sandbox remains the only path for real
  weights (and since `d89f69a` needs `HARNESS_ALLOW_UNSANDBOXED_FRAMEWORKS=1`
  for them).
