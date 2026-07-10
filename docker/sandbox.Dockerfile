# No-egress sandbox image (T005): the CV runtime every tier's inference runs in.
# Containers from this image are started with --network none, read-only mounts,
# and CPU/memory caps by engine/sandbox/runner.py (Constitution IV, D1).
FROM python:3.11-slim

# system libs for pillow/opencv-style wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

# The sandbox process is what imports the REAL adapter runtimes: torch (CPU) +
# ultralytics for .pt detection, timm for classification, onnxruntime for
# .onnx — plus the light deps engine.sandbox.job needs. The harness code is
# bind-mounted read-only at run time, so the image never needs rebuilding for
# engine changes.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir \
    numpy pillow pyyaml sqlmodel pydantic \
    onnxruntime ultralytics timm

ENV PYTHONPATH=/srv/backend
# the job entrypoint is provided by the runner: python -m engine.sandbox.job
