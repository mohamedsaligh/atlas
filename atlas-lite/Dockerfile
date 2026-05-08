# syntax=docker/dockerfile:1.7
#
# Multi-stage container for the Atlas read API.
#
# Stage 1 (builder): installs the Python package and its dependencies
# into an isolated user-site under /root/.local so the runtime stage
# can copy a single tree and inherit nothing else from the build
# environment.
#
# Stage 2 (runtime): minimal slim image, non-root user, healthcheck,
# read-only-friendly. The default command serves the API on :8080;
# override the entrypoint or use `atlas` directly to invoke the CLI.
#
# Alternative runtime: substitute the FROM in stage 2 with
# `cgr.dev/chainguard/python:latest` for distroless / Wolfi if a
# stricter supply-chain posture is required. The COPY chown will
# need to match Chainguard's `nonroot` user (uid 65532).

ARG PYTHON_VERSION=3.13

# ── Stage 1 — builder ───────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --user .

# ── Stage 2 — runtime ──────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ATLAS_DB_PATH=/atlas/data/atlas.db \
    ATLAS_LOG_FORMAT=json \
    ATLAS_LOG_LEVEL=INFO \
    PATH=/home/atlas/.local/bin:$PATH

RUN groupadd --system atlas \
    && useradd  --system --gid atlas --uid 1001 --create-home atlas \
    && mkdir -p /atlas/data \
    && chown -R atlas:atlas /atlas

USER atlas
WORKDIR /atlas

# Bring in only the user-site tree from the builder. Nothing else
# crosses the stage boundary — no apt cache, no build deps, no source.
COPY --from=builder --chown=atlas:atlas /root/.local /home/atlas/.local

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys;\
sys.exit(0 if urllib.request.urlopen('http://localhost:8080/api/v1/health',timeout=2).status==200 else 1)" \
    || exit 1

ENTRYPOINT ["atlas"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
