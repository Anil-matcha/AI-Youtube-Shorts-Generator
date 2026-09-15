FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOCAL_OUTPUT_DIR=/data/output \
    SHORTS_STUDIO_DATA_DIR=/data \
    HF_HOME=/data/models \
    HUGGINGFACE_HUB_CACHE=/data/models/hub \
    XDG_CACHE_HOME=/data/cache \
    SHORTS_STUDIO_HEADLESS=true \
    SHORTS_STUDIO_BROWSER=true \
    SHORTS_PORT=7860

WORKDIR /app

ARG TARGETARCH

# FFmpeg handles rendering, Node gives yt-dlp its optional YouTube challenge
# runtime, and the small runtime libraries are required by OpenCV headless.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-docker.txt requirements-docker-arm64.txt ./
RUN python -m pip install --upgrade pip \
    && if [ "$TARGETARCH" = "arm64" ]; then \
         python -m pip install --no-cache-dir -r requirements-docker-arm64.txt; \
       else \
         python -m pip install --no-cache-dir -r requirements-docker.txt; \
       fi

COPY . .
RUN mkdir -p /data/output /data/cache /data/models \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin shorts \
    && chown -R shorts:shorts /app /data
USER shorts

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "7860"]
