from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic_settings import BaseSettings, SettingsConfigDict

from flowtts.inference import AudioConfig, FlowTTSPipeline, ModelConfig

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("thonburian_tts")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    output_dir: Path = Path(os.getenv("TTS_OUTPUT_DIR", "/workspace/outputs"))
    upload_dir: Path = Path(os.getenv("TTS_UPLOAD_DIR", "/workspace/uploads"))
    reference_dir: Path = Path(os.getenv("TTS_REFERENCE_DIR", "/workspace/reference-audio"))
    work_dir: Path = Path(os.getenv("TTS_WORK_DIR", "/workspace/tts-work"))
    static_dir: Path = Path("/app/frontend/dist")
    checkpoint: str = os.getenv(
        "TTS_CHECKPOINT",
        "hf://biodatlab/ThonburianTTS/megaF5/mega_f5_last.safetensors",
    )
    vocab_file: str = os.getenv(
        "TTS_VOCAB_FILE",
        "hf://biodatlab/ThonburianTTS/megaF5/mega_vocab.txt",
    )
    job_ttl_seconds: int = int(os.getenv("TTS_JOB_TTL_SECONDS", "1800"))
    max_upload_bytes: int = int(os.getenv("TTS_MAX_UPLOAD_BYTES", str(80 * 1024 * 1024)))
    max_text_chars: int = int(os.getenv("TTS_MAX_TEXT_CHARS", "2500"))
    max_reference_text_chars: int = int(os.getenv("TTS_MAX_REFERENCE_TEXT_CHARS", "1000"))


settings = Settings()
ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
JobStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class TTSJob:
    id: str
    text: str
    reference_text: str
    reference_path: str
    uploaded_reference: bool
    speed: float
    nfe_steps: int
    status: JobStatus = "queued"
    error: str | None = None
    output_path: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    def public(self) -> dict:
        data = asdict(self)
        data.pop("reference_path", None)
        data.pop("uploaded_reference", None)
        if self.status == "completed":
            data["download_url"] = f"/api/jobs/{self.id}/audio"
        return data


class TTSService:
    """Loads the GPU pipeline on first use and serializes inference safely."""

    def __init__(self) -> None:
        self.pipeline: FlowTTSPipeline | None = None
        self.load_lock = asyncio.Lock()

    async def ensure_loaded(self) -> FlowTTSPipeline:
        if self.pipeline is not None:
            return self.pipeline
        async with self.load_lock:
            if self.pipeline is None:
                logger.info("Loading ThonburianTTS checkpoint on %s", "CUDA" if torch.cuda.is_available() else "CPU")
                self.pipeline = await asyncio.to_thread(self._load_pipeline)
                logger.info("ThonburianTTS model is ready")
        return self.pipeline

    @staticmethod
    def _load_pipeline() -> FlowTTSPipeline:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_config = ModelConfig(
            device=device,
            model_type="F5",
            language="th",
            vocoder="vocos",
            ode_method="euler",
            use_ema=True,
            checkpoint=settings.checkpoint,
            vocab_file=settings.vocab_file,
            seed=-1,
        )
        audio_config = AudioConfig(
            silence_threshold=-45,
            max_audio_length=20000,
            cfg_strength=2.5,
            nfe_step=32,
            target_rms=0.1,
            cross_fade_duration=0.15,
            speed=1.0,
            min_silence_len=500,
            keep_silence=200,
            seek_step=10,
        )
        return FlowTTSPipeline(
            model_config=model_config,
            audio_config=audio_config,
            temp_dir=str(settings.work_dir / "pipeline-temp"),
        )

    async def synthesize(self, job: TTSJob) -> str:
        pipeline = await self.ensure_loaded()
        output_path = settings.output_dir / f"{job.id}.wav"

        def run() -> str:
            pipeline.audio_config.nfe_step = job.nfe_steps
            return pipeline(
                text=job.text,
                ref_voice=job.reference_path,
                ref_text=job.reference_text,
                output_file=str(output_path),
                speed=job.speed,
                check_duration=True,
            )

        return await asyncio.to_thread(run)


class JobManager:
    def __init__(self, service: TTSService) -> None:
        self.service = service
        self.jobs: dict[str, TTSJob] = {}
        self.gpu_lock = asyncio.Lock()

    def add(self, job: TTSJob) -> None:
        self.cleanup_expired()
        self.jobs[job.id] = job
        asyncio.create_task(self._run(job.id))

    async def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        async with self.gpu_lock:
            job.status = "running"
            job.started_at = time.time()
            try:
                job.output_path = await self.service.synthesize(job)
                job.status = "completed"
            except Exception:
                logger.exception("TTS job %s failed", job.id)
                job.status = "failed"
                job.error = "ไม่สามารถสร้างเสียงได้ กรุณาตรวจข้อความและไฟล์เสียงต้นแบบ แล้วลองอีกครั้ง"
            finally:
                job.completed_at = time.time()
                if job.uploaded_reference:
                    Path(job.reference_path).unlink(missing_ok=True)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

    def get(self, job_id: str) -> TTSJob:
        self.cleanup_expired()
        job = self.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="ไม่พบงานนี้ หรือไฟล์หมดอายุแล้ว")
        return job

    def cleanup_expired(self) -> None:
        cutoff = time.time() - settings.job_ttl_seconds
        expired = [job_id for job_id, job in self.jobs.items() if job.created_at < cutoff]
        for job_id in expired:
            job = self.jobs.pop(job_id)
            if job.output_path:
                Path(job.output_path).unlink(missing_ok=True)
            if job.uploaded_reference:
                Path(job.reference_path).unlink(missing_ok=True)


service = TTSService()
manager = JobManager(service)
app = FastAPI(title="Thonburian TTS", version="1.0.0", docs_url=None, redoc_url=None)
cleanup_task: asyncio.Task[None] | None = None


async def cleanup_loop() -> None:
    interval = max(30, min(300, settings.job_ttl_seconds // 4))
    while True:
        await asyncio.sleep(interval)
        manager.cleanup_expired()


@app.on_event("startup")
async def create_directories() -> None:
    global cleanup_task
    for directory in [settings.output_dir, settings.upload_dir, settings.reference_dir, settings.work_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def stop_cleanup_loop() -> None:
    global cleanup_task
    if cleanup_task is not None:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        cleanup_task = None


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def validate_audio_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(ALLOWED_AUDIO_SUFFIXES))
        raise HTTPException(status_code=415, detail=f"รองรับเฉพาะไฟล์เสียง: {supported}")
    return suffix


async def save_upload(upload: UploadFile) -> Path:
    filename = upload.filename or "reference.wav"
    suffix = validate_audio_suffix(filename)
    destination = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"ไฟล์เสียงต้องมีขนาดไม่เกิน {settings.max_upload_bytes // 1024 // 1024} MB",
                    )
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return destination


def resolve_workspace_reference(filename: str) -> Path:
    candidate = (settings.reference_dir / filename).resolve()
    root = settings.reference_dir.resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์เสียงใน /workspace/reference-audio")
    validate_audio_suffix(candidate.name)
    return candidate


def validate_job_inputs(text: str, reference_text: str, speed: float, nfe_steps: int) -> None:
    if not text or not text.strip():
        raise HTTPException(status_code=422, detail="กรุณากรอกข้อความที่ต้องการสร้างเสียง")
    if len(text.strip()) > settings.max_text_chars:
        raise HTTPException(status_code=422, detail=f"ข้อความยาวได้ไม่เกิน {settings.max_text_chars:,} ตัวอักษร")
    if not reference_text or not reference_text.strip():
        raise HTTPException(status_code=422, detail="กรุณากรอกข้อความที่พูดอยู่ในเสียงต้นแบบ")
    if len(reference_text.strip()) > settings.max_reference_text_chars:
        raise HTTPException(status_code=422, detail="ข้อความกำกับเสียงต้นแบบยาวเกินกำหนด")
    if not 0.7 <= speed <= 1.3:
        raise HTTPException(status_code=422, detail="ความเร็วต้องอยู่ระหว่าง 0.7 และ 1.3")
    if nfe_steps not in {16, 24, 32, 40, 48}:
        raise HTTPException(status_code=422, detail="ค่า Quality ไม่ถูกต้อง")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "model_loaded": service.pipeline is not None,
        "queue_depth": sum(job.status in {"queued", "running"} for job in manager.jobs.values()),
    }


@app.get("/api/reference-files")
async def reference_files() -> dict:
    files = []
    if settings.reference_dir.exists():
        for path in sorted(settings.reference_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in ALLOWED_AUDIO_SUFFIXES:
                files.append({"name": path.name, "size_bytes": path.stat().st_size})
    return {"files": files, "directory": str(settings.reference_dir)}


@app.post("/api/jobs", status_code=202)
async def create_job(
    text: str = Form(...),
    reference_text: str = Form(...),
    speed: float = Form(1.0),
    nfe_steps: int = Form(32),
    reference_file: UploadFile | None = File(default=None),
    workspace_reference: str | None = Form(default=None),
) -> dict:
    validate_job_inputs(text, reference_text, speed, nfe_steps)
    if reference_file is not None and workspace_reference:
        raise HTTPException(status_code=422, detail="เลือกได้เพียงไฟล์อัปโหลดหรือไฟล์ใน workspace อย่างใดอย่างหนึ่ง")
    if reference_file is not None:
        reference_path = await save_upload(reference_file)
        uploaded_reference = True
    elif workspace_reference:
        reference_path = resolve_workspace_reference(workspace_reference)
        uploaded_reference = False
    else:
        raise HTTPException(status_code=422, detail="กรุณาเลือกหรืออัปโหลดไฟล์เสียงต้นแบบ")

    job = TTSJob(
        id=uuid.uuid4().hex,
        text=text.strip(),
        reference_text=reference_text.strip(),
        reference_path=str(reference_path),
        uploaded_reference=uploaded_reference,
        speed=speed,
        nfe_steps=nfe_steps,
    )
    manager.add(job)
    return job.public()


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    return manager.get(job_id).public()


@app.get("/api/jobs/{job_id}/audio")
async def download_audio(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=409, detail="ไฟล์เสียงยังไม่พร้อมดาวน์โหลด")
    output_path = Path(job.output_path)
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์เสียง หรือไฟล์หมดอายุแล้ว")
    return FileResponse(
        output_path,
        media_type="audio/wav",
        filename="thonburian-tts.wav",
        headers={"Cache-Control": "no-store"},
    )


if settings.static_dir.exists():
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")


@app.get("/{requested_path:path}")
async def serve_frontend(requested_path: str) -> FileResponse:
    index_file = settings.static_dir / "index.html"
    candidate = (settings.static_dir / requested_path).resolve()
    root = settings.static_dir.resolve()
    if requested_path and root in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    if not index_file.is_file():
        raise HTTPException(status_code=503, detail="UI build ยังไม่พร้อมใช้งาน")
    return FileResponse(index_file, headers={"Cache-Control": "no-store"})
