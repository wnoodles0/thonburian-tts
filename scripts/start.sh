#!/usr/bin/env bash
set -Eeuo pipefail

mkdir -p \
  "${HF_HOME}" \
  "${XDG_CACHE_HOME}" \
  "${TTS_OUTPUT_DIR}" \
  "${TTS_UPLOAD_DIR}" \
  "${TTS_REFERENCE_DIR}"

cleanup() {
  if [[ -n "${RUNPOD_START_PID:-}" ]] && kill -0 "${RUNPOD_START_PID}" 2>/dev/null; then
    kill "${RUNPOD_START_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Preserve the RunPod image's standard JupyterLab and SSH startup behavior.
# Its Jupyter token settings remain unchanged and protected by the base image.
if [[ -x /start.sh ]]; then
  /start.sh &
  RUNPOD_START_PID=$!
  sleep 2
fi

echo "Starting Thonburian TTS at 0.0.0.0:${TTS_PORT}"
exec uvicorn backend.main:app --host 0.0.0.0 --port "${TTS_PORT}" --proxy-headers --forwarded-allow-ips='*'
