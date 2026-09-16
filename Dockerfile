# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /build
ARG TARGETARCH

# Dependency manifests are copied before source so ordinary code edits reuse
# the expensive wheel-install layer.  BuildKit's cache keeps repeated beta
# builds fast without shipping a pip cache in the final image.
COPY requirements.txt requirements-docker.txt requirements-docker-arm64.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv "$VIRTUAL_ENV" \
    && if [ "$TARGETARCH" = "arm64" ]; then \
         python -m pip install -r requirements-docker-arm64.txt; \
       else \
         python -m pip install -r requirements-docker.txt; \
       fi


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH \
    LOCAL_OUTPUT_DIR=/data/output \
    SHORTS_STUDIO_DATA_DIR=/data \
    HF_HOME=/data/models \
    HUGGINGFACE_HUB_CACHE=/data/models/hub \
    XDG_CACHE_HOME=/data/cache \
    SHORTS_STUDIO_HEADLESS=true \
    SHORTS_STUDIO_BROWSER=true \
    SHORTS_PORT=7860

WORKDIR /app

# Runtime-only OS packages.  Build tools, pip, and the source tree's tests and
# release material stay out of the production image.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dependencies /opt/venv /opt/venv
COPY shorts_generator ./shorts_generator
COPY web ./web
COPY pyproject.toml README.md LICENSE ./

RUN mkdir -p /data/output /data/cache /data/models \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin shorts \
    && chown -R shorts:shorts /app /data
USER shorts

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "7860"]
