# No-egress sandbox image (T005): the CV runtime every tier's inference runs in.
# Containers from this image are started with --network none, read-only mounts,
# and CPU/memory caps by engine/sandbox/runner.py (Constitution IV, D1).
FROM python:3.11-slim

# system libs for pillow/opencv-style wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

# runtime deps only — the harness code is bind-mounted read-only at run time,
# so the image never needs rebuilding for engine changes
COPY backend/pyproject.toml /tmp/pyproject.toml
RUN pip install --no-cache-dir \
    numpy pillow pyyaml sqlmodel pydantic \
    torch --index-url https://download.pytorch.org/whl/cpu || \
    pip install --no-cache-dir numpy pillow pyyaml sqlmodel pydantic

ENV PYTHONPATH=/srv/backend
# the job entrypoint is provided by the runner: python -m engine.sandbox.job
