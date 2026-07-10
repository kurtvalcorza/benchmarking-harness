# Datasets — licenses and fetch-not-commit policy

**This repository is code-only.** No third-party dataset, no model weights, no
restricted media is ever committed (Constitution II; enforced by
`backend/tests/contract/test_no_restricted_data.py` on every push, and by
`.gitignore` blocking `data/`, `models/`, `*.pt`, `*.onnx`, …).

## What IS committed

| Path | Content | License |
|---|---|---|
| `samples/benchmarks/*` | Tiny **procedurally generated** synthetic images + annotations (drawn rectangles on noise, produced by `scripts/gen_samples.py`) | Owned — generated in-repo, MIT like the code |
| `samples/golden/*` | Same synthetic generator; the demo Golden Test Sets | Owned |
| `samples/models/*.stub.json` | Toy "stub model" weight files (JSON skill descriptors) | Owned |

Nothing under `samples/` derives from any third-party dataset.

## What is FETCHED (never committed)

| Dataset | Used for | How | License terms |
|---|---|---|---|
| Open Images V7 (subset) | Tier-1 stand-in + Golden Test Set stand-in for detection/classification | `scripts/fetch_open_images.py --class detection --n 200` (FiftyOne zoo) | Annotations **CC BY 4.0**; images individually **CC BY 2.0** (verify per image for redistribution — we don't redistribute, we fetch) |

Fetched data lands in `data/` (gitignored). Each registered Golden Test Set is
checksummed at registration; the checksum is stamped on every Tier-2 result
(FR-018) so any content drift is detectable.

## Referenced but NOT used in the POC

The Tier-1 registry names the *real* benchmarks each slot stands in for (COCO,
LVIS, ImageNet, Cityscapes, COCO Keypoints, CULane, WFLW). Several of these
carry **research-only / non-commercial** terms — which is exactly why the POC
substitutes permissive stand-ins and why fetch scripts, not committed copies,
are the only path to real data. Before using any of them, review their terms:

- ImageNet — research, non-commercial
- Cityscapes — research, non-commercial
- CULane — research
- WFLW — derived from a research dataset

## Adverse-condition perturbations

Rain / low-light / fog are produced by applying **permissively licensed
transforms** (self-contained PIL/NumPy implementations in
`backend/engine/perturb/transforms.py`; optionally `imagecorruptions`
(Apache-2.0) / `albumentations` (MIT) with the `ml` extra) to owned or
permissive data at evaluation time. No perturbed derivative of restricted data
is ever created or stored in the repo.
