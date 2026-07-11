# No-egress sandbox image: the CV runtime every tier's inference runs in.
# Containers from this image are started with --network none, read-only mounts,
# cap_drop ALL, no-new-privileges, a seccomp profile, and CPU/memory/PID caps by
# engine/sandbox/runner.py (Constitution IV, security-boundary.md).
#
# Base image pinned to a specific patch tag for reproducibility (T007); pin by
# @sha256 digest for a production release (see docker/api.Dockerfile).
FROM python:3.11.9-slim-bookworm

# A non-root identity the runner runs the model process as (defence in depth:
# the runner also sets user=65532:65532 at launch).
RUN groupadd --gid 65532 nonroot \
    && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin nonroot

# system libs for pillow/opencv-style wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

# Pinned model-runtime inputs (T007): torch (CPU) + ultralytics for .pt
# detection, timm for classification, onnxruntime for .onnx, plus the light deps
# engine.sandbox.job needs. Versions are pinned so a rebuild is reproducible;
# the on-hardware sandbox runtime probe (T069) is the gate that confirms the set
# co-resolves and runs. The harness code is bind-mounted read-only at run time,
# so the image never needs rebuilding for engine changes.
RUN pip install --no-cache-dir torch==2.4.1 torchvision==0.19.1 \
    --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir \
    numpy==1.26.4 pillow==10.4.0 pyyaml==6.0.2 sqlmodel==0.0.22 pydantic==2.9.2 \
    onnxruntime==1.19.2 ultralytics==8.3.0 timm==1.0.11

ENV PYTHONPATH=/srv/backend
USER 65532:65532
# the job entrypoint is provided by the runner: python -m engine.sandbox.job
