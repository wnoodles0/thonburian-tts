"""Offline smoke test for the FastAPI service; it replaces model inference with a tiny stub."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

workspace = Path(tempfile.mkdtemp(prefix="thonburian-api-test-"))
os.environ["TTS_OUTPUT_DIR"] = str(workspace / "outputs")
os.environ["TTS_UPLOAD_DIR"] = str(workspace / "uploads")
os.environ["TTS_REFERENCE_DIR"] = str(workspace / "reference-audio")
os.environ["TTS_WORK_DIR"] = str(workspace / "work")
os.environ["TTS_JOB_TTL_SECONDS"] = "3600"

# The real model is deliberately not downloaded for this API-only test.
fake_inference = types.ModuleType("flowtts.inference")
class ModelConfig:  # noqa: D101
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
class AudioConfig:  # noqa: D101
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
class FlowTTSPipeline:  # noqa: D101
    def __init__(self, **kwargs):
        self.audio_config = kwargs.get("audio_config")
fake_inference.ModelConfig = ModelConfig
fake_inference.AudioConfig = AudioConfig
fake_inference.FlowTTSPipeline = FlowTTSPipeline
sys.modules["flowtts.inference"] = fake_inference

fake_torch = types.ModuleType("torch")
class FakeCuda:
    @staticmethod
    def is_available() -> bool:
        return False
    @staticmethod
    def empty_cache() -> None:
        return None
fake_torch.cuda = FakeCuda()
sys.modules["torch"] = fake_torch

from fastapi.testclient import TestClient  # noqa: E402
from backend import main  # noqa: E402

async def fake_synthesize(job: main.TTSJob) -> str:
    output = main.settings.output_dir / f"{job.id}.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    await asyncio.sleep(0.01)
    return str(output)

main.service.synthesize = fake_synthesize

with TestClient(main.app) as client:
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"

    invalid = client.post("/api/jobs", data={"text": "สวัสดี", "reference_text": "สวัสดี"})
    assert invalid.status_code == 422, invalid.text

    create = client.post(
        "/api/jobs",
        data={"text": "สวัสดีครับ", "reference_text": "สวัสดีครับ", "speed": "1.0", "nfe_steps": "32"},
        files={"reference_file": ("voice.wav", b"fake audio", "audio/wav")},
    )
    assert create.status_code == 202, create.text
    job_id = create.json()["id"]

    result = None
    for _ in range(20):
        result = client.get(f"/api/jobs/{job_id}")
        assert result.status_code == 200, result.text
        if result.json()["status"] == "completed":
            break
        import time
        time.sleep(0.05)
    assert result is not None and result.json()["status"] == "completed", result.text

    audio = client.get(f"/api/jobs/{job_id}/audio")
    assert audio.status_code == 200, audio.text
    assert audio.headers["content-type"].startswith("audio/wav")

print("API smoke test passed")
