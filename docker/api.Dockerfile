# API + worker image (compose services `api` and `worker`).
#
# Base image pinned to a specific patch tag for reproducibility (T007). For a
# production release, pin by immutable digest instead — obtain it with:
#   docker buildx imagetools inspect python:3.11.9-slim-bookworm
# and replace the tag with python:3.11.9-slim-bookworm@sha256:<digest>.
FROM python:3.11.9-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend /srv/backend
COPY samples /srv/samples
# Deterministic pip: no cache, and pip itself is the one already baked into the
# pinned base image. Production deployments should install from a committed
# uv.lock / hash-locked requirements (T001) rather than resolving at build time.
RUN pip install --no-cache-dir -e /srv/backend

WORKDIR /srv/backend
ENV HARNESS_SAMPLES_DIR=/srv/samples
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
