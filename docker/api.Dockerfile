# API + worker image (compose services `api` and `worker`)
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend /srv/backend
COPY samples /srv/samples
RUN pip install --no-cache-dir -e /srv/backend

WORKDIR /srv/backend
ENV HARNESS_SAMPLES_DIR=/srv/samples
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
