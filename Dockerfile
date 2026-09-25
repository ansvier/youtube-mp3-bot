# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.13-slim-trixie@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp DENO_DIR=/tmp/deno
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
COPY requirements.lock ./
RUN python -m pip install --require-hashes -r requirements.lock
COPY LICENSE THIRD_PARTY_NOTICES.md ./

FROM base AS media-runtime
# Current security-maintained FFmpeg from the signed Debian repositories.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM media-runtime AS worker
COPY media_worker/ ./media_worker/
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "media_worker", "--healthcheck"]
CMD ["python", "-m", "media_worker"]

FROM media-runtime AS test
COPY requirements-dev.lock ./
RUN python -m pip install --require-hashes -r requirements-dev.lock
COPY pyproject.toml ./
COPY media_worker/ ./media_worker/
COPY mp3_bot/ ./mp3_bot/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS bot
COPY media_worker/ ./media_worker/
COPY mp3_bot/ ./mp3_bot/
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "-m", "mp3_bot", "--healthcheck"]
CMD ["python", "-m", "mp3_bot"]
