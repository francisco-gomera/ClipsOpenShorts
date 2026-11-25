"""FastAPI endpoints for live clipping sessions and their deliverables."""
from __future__ import annotations

import os
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from live.config import (DEFAULT_CLIP_MAX_SECONDS, DEFAULT_CLIP_MIN_SECONDS,
                         MAX_CONFIGURABLE_CLIP_SECONDS, MIN_CONFIGURABLE_CLIP_SECONDS,
                         BLOCK_MINUTES)
from live.blocks import BlockManager
from live.resolver import LiveResolveError, _validate_youtube_url
from live.session import LiveSessionManager, SessionConflict, update_state

router = APIRouter(prefix="/api/live", tags=["live"])
_manager: LiveSessionManager | None = None
_output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
_owner_resolver = None
_access_check = None
_media_signer = None
_admission_check = None
_auth_context_resolver = None
_pipeline_key_resolver = None
_BLOCK_ACTIVE_SESSION_STATES = {"iniciando", "esperando", "capturando", "reconectando",
                               "deteniendo", "finalizando", "detenido_por_disco"}


def configure(*, output_dir=None, owner_resolver=None, access_check=None, media_signer=None,
              manager=None, admission_check=None, auth_context_resolver=None, auth_checker=None,
              pipeline_key_resolver=None):
    global _manager, _output_dir, _owner_resolver, _access_check, _media_signer, _admission_check
    global _auth_context_resolver, _pipeline_key_resolver
    if output_dir is not None:
        _output_dir = Path(output_dir).resolve()
    _owner_resolver = owner_resolver
    _access_check = access_check
    _media_signer = media_signer
    _admission_check = admission_check
    _auth_context_resolver = auth_context_resolver
    _pipeline_key_resolver = pipeline_key_resolver
    if auth_checker is not None and _manager is not None:
        _manager.auth_checker = auth_checker
    if manager is not None:
        _manager = manager
    elif _manager is None or _manager.output_dir != _output_dir:
        _manager = LiveSessionManager(_output_dir, auth_checker=auth_checker)
    elif auth_checker is not None:
        _manager.auth_checker = auth_checker


def _sessions() -> LiveSessionManager:
    global _manager
    if _manager is None:
        _manager = LiveSessionManager(_output_dir)
    return _manager


def has_active_session() -> bool:
    return _sessions().active_session() is not None


async def _authorize_request(request: Request):
    if _access_check:
        await _access_check(request)
    if _owner_resolver:
        return await _owner_resolver(request)
    return None


async def _get_owned_session(request: Request, session_id: str):
    owner_id = await _authorize_request(request)
    try:
        state = _sessions().get(session_id)
    except FileNotFoundError:
        state = None
    if not state:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    if owner_id is not None and (state.get("user_id") is None
                                 or str(state["user_id"]) != str(owner_id)):
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return state


def _present(state: dict) -> dict:
    result = dict(state)
    result.pop("auth_session_ref", None)
    result.pop("worker_pid", None)
    result.pop("worker_proc_start", None)
    result.pop("auth_expires_at", None)
    result.setdefault("min_clip_seconds", DEFAULT_CLIP_MIN_SECONDS)
    result.setdefault("max_clip_seconds", DEFAULT_CLIP_MAX_SECONDS)
    result.setdefault("capture_started_at", None)
    result.setdefault("capture_ended_at", None)
    result.setdefault("capture_elapsed_seconds", 0)
    result.setdefault("stats", {"detectados": len(state.get("candidates", [])),
                                 "descartados": 0, "errores": 0,
                                 "renderizados": len(state.get("clips", []))})
    started_at = result.get("capture_started_at")
    if started_at is not None:
        ended_at = result.get("capture_ended_at")
        if ended_at is None and result.get("status") in {"detenido", "error"}:
            ended_at = result.get("ended_at")
            if ended_at is not None:
                result["capture_ended_at"] = ended_at
        end = float(ended_at) if ended_at is not None else time.time()
        result["capture_elapsed_seconds"] = max(0, int(end - float(started_at)))
    clips = []
    for item in state.get("clips", []):
        clip = dict(item)
        rel = clip.get("video_url")
        if isinstance(rel, str) and _media_signer:
            clip["video_url"] = _media_signer(rel)
            clip["download_url"] = _media_signer(rel)
        clips.append(clip)
    result["clips"] = clips
    result["result"] = {"shorts": clips}
    result["queue"] = state.get("queue", [])
    return result


def _present_summary(state: dict) -> dict:
    """Small list payload; callers fetch the full, bounded state by id."""
    summary = {key: state.get(key) for key in (
        "id", "status", "created_at", "titulo", "mensaje", "segments", "segments_total",
        "stats", "capture_started_at", "capture_ended_at", "capture_elapsed_seconds",
        "reconnections", "asr_status", "render_priority_paused", "mode", "block_minutes",
        "blocks_summary",
    )}
    summary["stats"] = state.get("stats") or {
        "detectados": len(state.get("candidates", [])), "descartados": 0,
        "errores": 0, "renderizados": len(state.get("clips", []))}
    summary["segments_total"] = state.get("segments_total", state.get("segments", 0))
    return summary | {"clips_count": len(state.get("clips", []))}


@router.get("/health")
async def live_health():
    return {"status": "ok", "fase": "L6"}


@router.get("")
async def list_live_sessions(request: Request):
    owner_id = await _authorize_request(request)
    sessions = []
    for directory in _sessions().output_dir.iterdir():
        if not directory.is_dir():
            continue
        try:
            state = _sessions().get(directory.name)
        except FileNotFoundError:
            state = None
        if not state or (owner_id is not None and (state.get("user_id") is None
                                                   or str(state["user_id"]) != str(owner_id))):
            continue
        sessions.append(_present_summary(state))
    sessions.sort(key=lambda state: state.get("created_at", 0), reverse=True)
    return {"sessions": sessions}


class LiveCreateRequest(BaseModel):
    url: str
    min_clip_seconds: int = Field(default=DEFAULT_CLIP_MIN_SECONDS,
                                  ge=MIN_CONFIGURABLE_CLIP_SECONDS, le=MAX_CONFIGURABLE_CLIP_SECONDS)
    max_clip_seconds: int = Field(default=DEFAULT_CLIP_MAX_SECONDS,
                                  ge=MIN_CONFIGURABLE_CLIP_SECONDS, le=MAX_CONFIGURABLE_CLIP_SECONDS)
    mode: str = "reactive"
    block_minutes: int = BLOCK_MINUTES

    @model_validator(mode="after")
    def validate_clip_range(self):
        if self.min_clip_seconds > self.max_clip_seconds:
            raise ValueError("La duración mínima no puede superar a la máxima.")
        if self.mode not in {"reactive", "blocks"}:
            raise ValueError("El modo LIVE no es válido")
        if self.block_minutes not in {20, 30, 40, 60}:
            raise ValueError("La duración del bloque debe ser 20, 30, 40 o 60 minutos")
        return self


class LiveStopRequest(BaseModel):
    modo: str = "terminar_pendientes"


class LiveClipUpdate(BaseModel):
    video_title_for_youtube_short: str | None = Field(default=None, max_length=120)
    video_description_for_youtube_short: str | None = Field(default=None, max_length=5000)
    video_description_for_tiktok: str | None = Field(default=None, max_length=2200)
    video_description_for_instagram: str | None = Field(default=None, max_length=2200)
    viral_hook_text: str | None = Field(default=None, max_length=300)


@router.post("", status_code=202)
async def create_live_session(body: LiveCreateRequest, request: Request):
    owner_id = await _authorize_request(request)
    try:
        _validate_youtube_url(body.url)
    except LiveResolveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if _admission_check:
        _admission_check()
    auth_context = await _auth_context_resolver(request) if _auth_context_resolver else None
    try:
        create_options = {"user_id": owner_id,
                          "min_clip_seconds": body.min_clip_seconds,
                          "max_clip_seconds": body.max_clip_seconds,
                          }
        if body.mode != "reactive" or body.block_minutes != BLOCK_MINUTES:
            create_options.update({"mode": body.mode, "block_minutes": body.block_minutes})
        if body.mode == "blocks" and _pipeline_key_resolver:
            pipeline_api_key = _pipeline_key_resolver()
            if pipeline_api_key:
                create_options["pipeline_api_key"] = pipeline_api_key
        if auth_context is not None:
            create_options["auth_context"] = auth_context
        state = _sessions().create(body.url, **create_options)
    except SessionConflict as exc:
        same_owner = str(exc.state.get("user_id")) == str(owner_id)
        detail = {"reason": "live_session_active", "status": exc.state.get("status"),
                  "stopping": exc.state.get("status") in {"deteniendo", "finalizando"}}
        if same_owner:
            detail["session_id"] = exc.state.get("id")
        raise HTTPException(status_code=409, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo iniciar live clipping") from exc
    return _present(state)


@router.get("/{session_id}")
async def get_live_session(session_id: str, request: Request):
    return _present(await _get_owned_session(request, session_id))


@router.get("/{session_id}/blocks")
async def get_live_blocks(session_id: str, request: Request, offset: int = 0, limit: int = 50):
    state = await _get_owned_session(request, session_id)
    if state.get("mode") != "blocks":
        raise HTTPException(status_code=404, detail="La sesión no usa el modo por bloques")
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Paginación inválida")
    manager = BlockManager(_sessions()._directory(session_id),
                           block_minutes=state.get("block_minutes", BLOCK_MINUTES),
                           recover=state.get("status") not in _BLOCK_ACTIVE_SESSION_STATES)
    return {"blocks": manager.blocks(offset=offset, limit=limit),
            "summary": manager.summary(), "offset": offset, "limit": limit}


@router.post("/{session_id}/blocks/{block_id}/retry", status_code=202)
async def retry_live_block(session_id: str, block_id: str, request: Request):
    state = await _get_owned_session(request, session_id)
    if state.get("mode") != "blocks":
        raise HTTPException(status_code=404, detail="La sesión no usa el modo por bloques")
    active = state.get("status") in _BLOCK_ACTIVE_SESSION_STATES
    manager = BlockManager(_sessions()._directory(session_id),
                           block_minutes=state.get("block_minutes", BLOCK_MINUTES), recover=not active)
    try:
        block = manager.get(block_id)
        if block.get("phase") == "error":
            block = manager.retry(block_id)
        elif active or block.get("phase") not in {"cerrado", "en_cola"}:
            raise ValueError("Este bloque todavía no se puede reintentar")
        if not active:
            key = _pipeline_key_resolver() if _pipeline_key_resolver else None
            _sessions().resume_blocks(session_id, pipeline_api_key=key)
        return block
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bloque no encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/blocks/{block_id}/omit", status_code=202)
async def omit_live_block(session_id: str, block_id: str, request: Request):
    state = await _get_owned_session(request, session_id)
    if state.get("mode") != "blocks":
        raise HTTPException(status_code=404, detail="La sesión no usa el modo por bloques")
    active = state.get("status") in _BLOCK_ACTIVE_SESSION_STATES
    manager = BlockManager(_sessions()._directory(session_id),
                           block_minutes=state.get("block_minutes", BLOCK_MINUTES), recover=not active)
    try:
        block = manager.omit(block_id)
        directory = _sessions()._directory(session_id)
        update_state(directory, lambda live_state: live_state.update(
            blocks_summary=manager.summary()))
        if not active and manager.summary()["pendientes"]:
            key = _pipeline_key_resolver() if _pipeline_key_resolver else None
            _sessions().resume_blocks(session_id, pipeline_api_key=key)
        return block
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bloque no encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/stop", status_code=202)
async def stop_live_session(session_id: str, body: LiveStopRequest, request: Request):
    await _get_owned_session(request, session_id)
    try:
        state = _sessions().stop(session_id, body.modo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _present(state)


@router.post("/stop-owned", status_code=202)
async def stop_owned_live_sessions(request: Request):
    owner_id = await _authorize_request(request)
    return {"sessions": [_present(state) for state in stop_owned_sessions(str(owner_id), "logout")]}


def stop_owned_sessions(owner_id: str, reason: str = "auth_expired") -> list[dict]:
    """Request graceful cancellation for only the owner's active Live workers."""
    stopped = []
    manager = _sessions()
    for directory in manager.output_dir.iterdir():
        if not directory.is_dir():
            continue
        try:
            state = manager.get(directory.name)
        except FileNotFoundError:
            continue
        if (not state or str(state.get("user_id")) != str(owner_id)
                or state.get("status") not in {"iniciando", "esperando", "capturando",
                                               "reconectando", "deteniendo", "finalizando"}):
            continue
        state = manager.stop(state["id"], "detener_ya", reason=reason)
        if state:
            stopped.append(state)
    return stopped


@router.patch("/{session_id}/clips/{clip_index}")
async def update_live_clip(session_id: str, clip_index: int, body: LiveClipUpdate, request: Request):
    await _get_owned_session(request, session_id)
    updates = body.model_dump(exclude_none=True)
    directory = _sessions()._directory(session_id)
    def apply_update(state):
        clips = state.get("clips", [])
        if clip_index < 0 or clip_index >= len(clips):
            raise HTTPException(status_code=404, detail="Clip no encontrado")
        clips[clip_index].update(updates)
        clips[clip_index]["metadata_edited_at"] = time.time()
        state["clips"] = clips
    state = update_state(directory, apply_update)
    return _present(state)


def _clip_file(session_id: str, state: dict, clip_index: int):
    clips = state.get("clips", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip no encontrado")
    filename = str(clips[clip_index].get("file") or "")
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Clip no encontrado")
    path = _sessions()._directory(session_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Archivo de clip no encontrado")
    return path, clips[clip_index]


@router.get("/{session_id}/download/{clip_index}")
async def download_live_clip(session_id: str, clip_index: int, request: Request):
    state = await _get_owned_session(request, session_id)
    path, _clip = _clip_file(session_id, state, clip_index)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/{session_id}/download.zip")
async def download_live_zip(session_id: str, request: Request):
    state = await _get_owned_session(request, session_id)
    directory = _sessions()._directory(session_id)
    work_dir = directory / ".live_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, archive = tempfile.mkstemp(prefix="live-download-", suffix=".zip",
                                   dir=str(work_dir))
    os.close(fd)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for index, clip in enumerate(state.get("clips", []), start=1):
                path, clip = _clip_file(session_id, state, index - 1)
                bundle.write(path, path.name)
                srt_name = str(clip.get("srt_file") or "")
                if srt_name and Path(srt_name).name == srt_name:
                    srt = directory / srt_name
                    if srt.is_file():
                        bundle.write(srt, srt.name)
                description = "\n".join([
                    str(clip.get("video_title_for_youtube_short") or ""),
                    str(clip.get("viral_hook_text") or ""),
                    str(clip.get("video_description_for_tiktok") or ""),
                    str(clip.get("video_description_for_instagram") or ""),
                    str(clip.get("video_description_for_youtube_short") or ""),
                    str(clip.get("why") or ""),
                ]).strip() + "\n"
                bundle.writestr(f"clip_{index}_descripciones.txt", description)
    except Exception:
        Path(archive).unlink(missing_ok=True)
        raise
    from starlette.background import BackgroundTask
    return FileResponse(archive, media_type="application/zip", filename="clips_en_vivo.zip",
                        background=BackgroundTask(lambda: Path(archive).unlink(missing_ok=True)))
