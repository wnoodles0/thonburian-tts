# syntax=docker/dockerfile:1.7

# Build the React UI separately to keep Node.js out of the final GPU image.
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# RunPod's PyTorch image keeps JupyterLab and SSH startup support.
FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    HF_HOME=/workspace/models/huggingface \
    XDG_CACHE_HOME=/workspace/cache \
    TTS_OUTPUT_DIR=/workspace/outputs \
    TTS_UPLOAD_DIR=/workspace/uploads \
    TTS_REFERENCE_DIR=/workspace/reference-audio \
    TTS_JOB_TTL_SECONDS=1800 \
    TTS_PORT=7777

WORKDIR /app

RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runpod.txt ./
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r requirements-runpod.txt

COPY flowtts/ ./flowtts/
COPY backend/ ./backend/
COPY assets/ ./assets/
COPY scripts/start.sh /app/scripts/start.sh
COPY --from=frontend-build /frontend/dist /app/frontend/dist

RUN mkdir -p \
      /workspace/models/huggingface \
      /workspace/cache \
      /workspace/outputs \
      /workspace/uploads \
      /workspace/reference-audio \
    && chmod +x /app/scripts/start.sh

# RunPod maps these internal HTTP ports through its proxy when configured in the template.
EXPOSE 7777 8888

CMD ["/app/scripts/start.sh"]
