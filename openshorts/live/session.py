"""Live session persistence and child-process lifecycle."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import (DEFAULT_CLIP_MAX_SECONDS, DEFAULT_CLIP_MIN_SECONDS,
                     LIVE_HISTORY_CANDIDATES, BLOCK_MINUTES,
                     validate_clip_duration_range)


_SESSION_ID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$", re.I)
_TERMINAL = {"detenido", "error"}
_ACTIVE = {"iniciando", "esperando", "capturando", "reconectando", "deteniendo", "finalizando"}
_ACTIVE.add("detenido_por_disco")
_STATE_LOCKS_GUARD = threading.Lock()
_STATE_LOCKS: dict[str, threading.RLock] = {}


class SessionConflict(ValueError):
    def __init__(self, state):
        super().__init__("Ya existe una sesión LIVE activa")
        self.state = state


def _proc_start_time(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return raw[raw.rfind(")") + 2:].split()[19]
    except (OSError, IndexError, ValueError):
        return None


def _proc_matches_worker(pid: int, session_id: str, start_time: str | None = None) -> bool:
    try:
        proc = Path(f"/proc/{pid}")
        if start_time and _proc_start_time(pid) != str(start_time):
            return False
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        environ = (proc / "environ").read_bytes().split(b"\0")
        return "live_worker.py" in cmdline and f"LIVE_SESSION_ID={session_id}".encode() in environ
    except OSError:
        return False


def _find_worker_pid(session_id: str) -> int | None:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        if _proc_matches_worker(pid, session_id):
            return pid
    return None


def _direct_ffmpeg_children(parent_pid: int) -> list[int]:
    children = []
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return children
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            fields = raw[raw.rfind(")") + 2:].split()
            if int(fields[1]) != int(parent_pid):
                continue
            args = (entry / "cmdline").read_bytes().split(b"\0")
            if args and Path(args[0].decode(errors="replace")).name.startswith("ffmpeg"):
                children.append(int(entry.name))
        except (OSError, IndexError, ValueError):
            continue
    return children


def _proc_is_ffmpeg(pid: int, start_time: str | None) -> bool:
    try:
        if start_time and _proc_start_time(pid) != str(start_time):
            return False
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return bool(args and Path(args[0].decode(errors="replace")).name.startswith("ffmpeg"))
    except OSError:
        return False


@contextmanager
def _state_file_lock(directory: Path):
    lock_path = directory / ".live_state.lock"
    key = str(lock_path.resolve())
    with _STATE_LOCKS_GUARD:
        thread_lock = _STATE_LOCKS.setdefault(key, threading.RLock())
    thread_lock.acquire()
    handle = lock_path.open("a+")
    locked = False
    try:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            locked = True
        except ImportError:
            pass
        yield
    finally:
        if locked:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except Exception:
                pass
        handle.close()
        thread_lock.release()


def _write_state_unlocked(directory: Path, state: dict) -> None:
    target = directory / "live_state.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, target)
    if state.get("clips"):
        metadata = directory / "live_metadata.json"
        payload = {"shorts": state["clips"]}
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            if json.loads(metadata.read_text(encoding="utf-8")) == payload:
                return
        except (OSError, ValueError):
            pass
        temporary_metadata = metadata.with_suffix(".tmp")
        temporary_metadata.write_text(serialized, encoding="utf-8")
        os.replace(temporary_metadata, metadata)


_CANDIDATE_ACTIVE = {"detectado", "evaluando", "en_cola", "renderizando"}


def _trim_candidate_history(state: dict) -> None:
    candidates = state.get("candidates", [])
    terminal = [item for item in candidates if item.get("status") not in _CANDIDATE_ACTIVE]
    keep_ids = {id(item) for item in terminal[-LIVE_HISTORY_CANDIDATES:]}
    state["candidates"] = [item for item in candidates
                           if item.get("status") in _CANDIDATE_ACTIVE or id(item) in keep_ids]


def _clip_identity(clip: dict):
    for key in ("id", "source_window_id", "file"):
        value = clip.get(key)
        if value not in (None, ""):
            return key, str(value)
    return None


def write_state(directory: str | Path, state: dict) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with _state_file_lock(directory):
        existing = read_state(directory)
        if existing:
            existing_clips = existing.get("clips", [])
            clips = state.get("clips", [])
            editable = ("video_title_for_youtube_short", "video_description_for_tiktok",
                        "video_description_for_instagram", "video_description_for_youtube_short",
                        "viral_hook_text")
            indexed = {_clip_identity(clip): clip for clip in clips if _clip_identity(clip)}
            for index, old_clip in enumerate(existing_clips):
                identity = _clip_identity(old_clip)
                current = indexed.get(identity) if identity else (clips[index] if index < len(clips) else None)
                if current is not None and old_clip.get("metadata_edited_at"):
                    for key in editable:
                        if key in old_clip and old_clip[key] not in (None, ""):
                            current[key] = old_clip[key]
                    current["metadata_edited_at"] = old_clip["metadata_edited_at"]
        _write_state_unlocked(directory, state)


def update_state(directory: str | Path, update) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with _state_file_lock(directory):
        state = read_state(directory) or {}
        update(state)
        _write_state_unlocked(directory, state)
        return state


def read_state(directory: str | Path) -> dict | None:
    try:
        return json.loads((Path(directory) / "live_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ensure_capture_fields(state: dict) -> bool:
    changed = False
    for key, value in (("capture_started_at", None), ("capture_ended_at", None),
                       ("capture_elapsed_seconds", 0)):
        if key not in state:
            state[key] = value
            changed = True
    return changed


def _finish_capture_fields(state: dict, ended_at: float | None = None) -> bool:
    """Freeze persisted elapsed time at the actual end of the FFmpeg capture."""
    _ensure_capture_fields(state)
    started_at = state.get("capture_started_at")
    if started_at is None:
        return False
    if state.get("capture_ended_at") is None:
        state["capture_ended_at"] = float(ended_at if ended_at is not None else time.time())
    state["capture_elapsed_seconds"] = max(
        0, int(float(state["capture_ended_at"]) - float(started_at)))
    return True


def _settle_interrupted_queue(state: dict, ended_at: float) -> bool:
    """Keep persisted clip progress truthful if its worker process disappeared."""
    changed = False
    for item in state.get("queue", []):
        if item.get("status") == "renderizando":
            item["failed_phase"] = item.get("phase")
            item.update({"status": "error", "phase": "error",
                         "error": "El worker terminó antes de completar esta fase",
                         "finished_at": ended_at, "updated_at": ended_at})
            changed = True
        elif item.get("status") in {"en_cola", "evaluando", "detectado"}:
            item.update({"status": "cancelado",
                         "reason": "El worker terminó antes de procesar el clip",
                         "finished_at": ended_at, "updated_at": ended_at})
            changed = True
    return changed


class LiveSessionManager:
    """Launches one isolated live worker per session and recovers stale state."""
    def __init__(self, output_dir: str | Path, *, worker_path: str | Path | None = None,
                 popen=subprocess.Popen, auth_checker=None, auth_check_interval: float = 5.0):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.worker_path = Path(worker_path or Path(__file__).resolve().parents[1] / "live_worker.py")
        self._popen = popen
        self.auth_checker = auth_checker
        self.auth_check_interval = max(1.0, float(auth_check_interval))
        self._processes = {}
        self._lock = threading.RLock()
        self._create_lock = threading.Lock()
        self.recover_stale()

    def _directory(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(str(session_id or "")):
            raise FileNotFoundError("Sesión no encontrada")
        target = (self.output_dir / session_id).resolve()
        if self.output_dir not in target.parents:
            raise FileNotFoundError("Sesión no encontrada")
        return target

    def recover_stale(self):
        for directory in self.output_dir.iterdir():
            if not directory.is_dir():
                continue
            state = read_state(directory)
            if not state:
                continue
            changed = _ensure_capture_fields(state)
            if (state.get("status") not in _TERMINAL or (state.get("worker_pid") and
                    _proc_matches_worker(int(state["worker_pid"]),
                                         str(state.get("id") or directory.name),
                                         state.get("worker_proc_start")))):
                session_id = str(state.get("id") or directory.name)
                pid = state.get("worker_pid")
                if pid and not _proc_matches_worker(int(pid), session_id, state.get("worker_proc_start")):
                    pid = None
                if not pid:
                    pid = _find_worker_pid(session_id)
                alive = bool(pid and _proc_matches_worker(
                    int(pid), session_id, state.get("worker_proc_start")))
                if alive:
                    state["worker_pid"] = int(pid)
                    state["worker_proc_start"] = state.get("worker_proc_start") or _proc_start_time(int(pid))
                    self._stop_orphan_worker(int(pid), session_id)
                    alive = _proc_matches_worker(int(pid), session_id, state.get("worker_proc_start"))
                if alive:
                    state.update({"status": "deteniendo", "mensaje": "Esperando el cierre del worker anterior",
                                  "end_reason": "server_recovery"})
                else:
                    ended_at = time.time()
                    state.update({"status": "detenido", "mensaje": "Sesión recuperada al reiniciar el servidor",
                                  "ended_at": ended_at, "end_reason": "server_recovery"})
                    _finish_capture_fields(state, ended_at)
                    changed = _settle_interrupted_queue(state, ended_at) or changed
                changed = True
            if state.get("status") in _TERMINAL:
                changed = _settle_interrupted_queue(
                    state, float(state.get("ended_at") or time.time())) or changed
            if changed:
                write_state(directory, state)

    def _stop_orphan_worker(self, pid: int, session_id: str, timeout: float = 20.0):
        if not _proc_matches_worker(pid, session_id):
            return
        ffmpeg_children = [(child, _proc_start_time(child)) for child in _direct_ffmpeg_children(pid)]
        stop_file = self.output_dir / session_id / "stop.request"
        try:
            stop_file.write_text("detener_ya", encoding="utf-8")
        except OSError:
            pass
        try:
            if os.name == "posix" and os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _proc_matches_worker(pid, session_id):
            time.sleep(0.25)
        for child_pid, start_time in ffmpeg_children:
            if not _proc_is_ffmpeg(child_pid, start_time):
                continue
            try:
                if os.getpgid(child_pid) == child_pid:
                    os.killpg(child_pid, signal.SIGINT)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        time.sleep(0.5)
        for child_pid, start_time in ffmpeg_children:
            if not _proc_is_ffmpeg(child_pid, start_time):
                continue
            try:
                if os.getpgid(child_pid) == child_pid:
                    os.killpg(child_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if _proc_matches_worker(pid, session_id):
            # FFmpeg uses its own process group, so stop verified direct children
            # before escalating the worker process group.
            for child_pid in _direct_ffmpeg_children(pid):
                try:
                    if os.getpgid(child_pid) == child_pid:
                        os.killpg(child_pid, signal.SIGINT)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            time.sleep(0.5)
            for child_pid in _direct_ffmpeg_children(pid):
                try:
                    if os.getpgid(child_pid) == child_pid:
                        os.killpg(child_pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            try:
                if os.name == "posix" and os.getpgid(pid) == pid:
                    os.killpg(pid, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def create(self, url: str, *, user_id=None, auth_context: dict | None = None,
               min_clip_seconds: int = DEFAULT_CLIP_MIN_SECONDS,
               max_clip_seconds: int = DEFAULT_CLIP_MAX_SECONDS,
               mode: str = "reactive", block_minutes: int = BLOCK_MINUTES,
               pipeline_api_key: str | None = None) -> dict:
        with self._create_lock:
            return self._create_unlocked(url, user_id=user_id, auth_context=auth_context,
                                          min_clip_seconds=min_clip_seconds,
                                          max_clip_seconds=max_clip_seconds,
                                          mode=mode, block_minutes=block_minutes,
                                          pipeline_api_key=pipeline_api_key)

    def _create_unlocked(self, url: str, *, user_id=None, auth_context: dict | None = None,
               min_clip_seconds: int = DEFAULT_CLIP_MIN_SECONDS,
               max_clip_seconds: int = DEFAULT_CLIP_MAX_SECONDS,
               mode: str = "reactive", block_minutes: int = BLOCK_MINUTES,
               pipeline_api_key: str | None = None) -> dict:
        min_clip_seconds, max_clip_seconds = validate_clip_duration_range(
            min_clip_seconds, max_clip_seconds)
        if mode not in {"reactive", "blocks"}:
            raise ValueError("El modo LIVE no es válido")
        if isinstance(block_minutes, bool) or block_minutes not in {20, 30, 40, 60}:
            raise ValueError("La duración del bloque debe ser 20, 30, 40 o 60 minutos")
        active = self.active_session()
        if active:
            raise SessionConflict(active)
        session_id = str(uuid.uuid4())
        directory = self._directory(session_id)
        directory.mkdir(parents=True, exist_ok=False)
        if user_id is not None:
            (directory / ".owner").write_text(str(user_id), encoding="utf-8")
        state = {"id": session_id, "url": url, "status": "iniciando", "created_at": time.time(),
                 "updated_at": time.time(), "clips": [], "candidates": [], "queue": [],
                 "notices": [], "segments": 0, "segments_total": 0,
                 "rtf": None, "user_id": str(user_id) if user_id else None,
                 "asr_status": "esperando", "render_priority_paused": False, "reconnections": 0,
                 "min_clip_seconds": min_clip_seconds, "max_clip_seconds": max_clip_seconds,
                 "mode": mode, "block_minutes": block_minutes,
                 "blocks_summary": {"total": 0, "pendientes": 0, "completados": 0},
                 "capture_started_at": None, "capture_ended_at": None,
                 "capture_elapsed_seconds": 0,
                 "auth_type": (auth_context or {}).get("type"),
                 "auth_expires_at": (auth_context or {}).get("expires_at"),
                 "auth_session_ref": (auth_context or {}).get("session_ref"),
                 "auth_status": "valid" if auth_context else "unmanaged"}
        if mode == "blocks":
            state["block_whisper_model"] = os.environ.get("LIVE_WHISPER_MODEL", "small")
        write_state(directory, state)
        environment = os.environ.copy()
        if mode == "blocks":
            from .child_env import child_env
            environment = child_env(environment)
            if pipeline_api_key:
                environment["GEMINI_API_KEY"] = pipeline_api_key
        environment.update({"LIVE_SESSION_ID": session_id, "LIVE_URL": url,
                            "LIVE_OUTPUT_DIR": str(directory),
                            "LIVE_STOP_FILE": str(directory / "stop.request"),
                            "LIVE_CLIP_MIN": str(min_clip_seconds),
                            "LIVE_CLIP_MAX": str(max_clip_seconds),
                            "LIVE_MODE": mode, "LIVE_BLOCK_MINUTES": str(block_minutes),
                            "AUTO_HOOK": "1", "AUTO_CAPTIONS": "1",
                            "CLIP_WORKERS": "1", "WATERMARK": "0",
                            "WHISPER_MODEL": os.environ.get("LIVE_WHISPER_MODEL", "small"),
                            "WHISPER_DEVICE": "cpu", "WHISPER_COMPUTE": "int8"})
        log = (directory / "worker.log").open("ab")
        command = [sys.executable, str(self.worker_path)]
        try:
            process = self._popen(command, cwd=str(self.worker_path.parent), env=environment,
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        except Exception:
            log.close()
            state.update({"status": "error", "mensaje": "No se pudo iniciar el proceso de live clipping",
                          "ended_at": time.time()})
            write_state(directory, state)
            raise
        log.close()
        with self._lock:
            self._processes[session_id] = process
            pid = getattr(process, "pid", None)
            if pid:
                state["worker_pid"] = int(pid)
                state["worker_proc_start"] = _proc_start_time(int(pid))
                write_state(directory, state)
        if self.auth_checker and auth_context:
            threading.Thread(target=self._monitor_auth, args=(session_id,),
                             name=f"live-auth-{session_id[:8]}", daemon=True).start()
        return state

    def _monitor_auth(self, session_id: str):
        while True:
            state = self.get(session_id)
            if not state or state.get("status") in _TERMINAL:
                return
            try:
                valid = self.auth_checker(state)
            except Exception:
                valid = None
            if valid is False and state.get("end_reason") != "logout":
                self.stop(session_id, "detener_ya", reason="auth_expired")
            time.sleep(self.auth_check_interval)

    def get(self, session_id: str) -> dict | None:
        directory = self._directory(session_id)
        state = read_state(directory)
        if not state:
            return None
        with self._lock:
            process = self._processes.get(session_id)
        process_alive = process.poll() is None if process is not None else bool(
            state.get("worker_pid") and _proc_matches_worker(
                int(state["worker_pid"]), session_id, state.get("worker_proc_start")))
        if process_alive and state.get("status") in _TERMINAL:
            state.update({"status": "deteniendo",
                          "mensaje": "Esperando la finalización real del worker"})
            state.setdefault("end_reason", "worker_outlived_terminal_state")
            (directory / "stop.request").write_text("detener_ya", encoding="utf-8")
            write_state(directory, state)
        if ((process is not None or state.get("worker_pid") is not None)
                and not process_alive and state.get("status") not in _TERMINAL):
            state.update({"status": "error", "mensaje": "El proceso de live clipping terminó inesperadamente",
                          "ended_at": time.time()})
            if state.get("end_reason") in {"auth_expired", "logout", "server_recovery",
                                            "worker_outlived_terminal_state"}:
                state["status"] = "detenido"
                state["mensaje"] = "La captura terminó de forma controlada"
            _finish_capture_fields(state, state.get("ended_at"))
            _settle_interrupted_queue(state, state["ended_at"])
            write_state(directory, state)
        elif state.get("status") in _TERMINAL and _settle_interrupted_queue(
                state, float(state.get("ended_at") or time.time())):
            write_state(directory, state)
        return state

    def active_session(self) -> dict | None:
        """Return the sole session that currently owns the media pipeline."""
        for directory in self.output_dir.iterdir():
            if not directory.is_dir():
                continue
            try:
                state = self.get(directory.name)
            except FileNotFoundError:
                continue
            if state and state.get("status") in _ACTIVE:
                return state
        return None

    def stop(self, session_id: str, mode: str = "terminar_pendientes", *, reason: str | None = None) -> dict | None:
        if mode not in ("terminar_pendientes", "detener_ya"):
            raise ValueError("Modo de parada inválido")
        directory = self._directory(session_id)
        state = self.get(session_id)
        if not state:
            return None
        if state.get("status") in _TERMINAL:
            return state
        (directory / "stop.request").write_text(mode, encoding="utf-8")
        state.update({"status": "deteniendo", "modo_parada": mode, "updated_at": time.time()})
        if reason:
            state["end_reason"] = reason
            if reason == "auth_expired":
                state["auth_status"] = "expired"
        write_state(directory, state)
        return state

    def resume_blocks(self, session_id: str, *, pipeline_api_key: str | None = None) -> dict:
        with self._create_lock:
            return self._resume_blocks_unlocked(session_id, pipeline_api_key=pipeline_api_key)

    def _resume_blocks_unlocked(self, session_id: str, *, pipeline_api_key: str | None = None) -> dict:
        """Restart a stopped block session as a processing-only worker."""
        directory = self._directory(session_id)
        state = self.get(session_id)
        if not state or state.get("mode") != "blocks":
            raise ValueError("La sesión no admite reprocesamiento por bloques")
        if state.get("status") in _ACTIVE:
            return state
        from .child_env import child_env
        (directory / "stop.request").unlink(missing_ok=True)
        state.update({"status": "finalizando", "mensaje": "Procesando bloques guardados",
                      "updated_at": time.time()})
        write_state(directory, state)
        environment = child_env()
        environment.update({"LIVE_SESSION_ID": session_id, "LIVE_URL": state.get("url", ""),
                            "LIVE_OUTPUT_DIR": str(directory),
                            "LIVE_STOP_FILE": str(directory / "stop.request"),
                            "LIVE_MODE": "blocks", "LIVE_RESUME_BLOCKS": "1",
                            "LIVE_BLOCK_MINUTES": str(state.get("block_minutes", BLOCK_MINUTES)),
                            "WHISPER_MODEL": str(state.get("block_whisper_model", "small")),
                            "LIVE_CLIP_MIN": str(state.get("min_clip_seconds", DEFAULT_CLIP_MIN_SECONDS)),
                            "LIVE_CLIP_MAX": str(state.get("max_clip_seconds", DEFAULT_CLIP_MAX_SECONDS)),
                            "AUTO_HOOK": "1", "AUTO_CAPTIONS": "1", "CLIP_WORKERS": "1",
                            "WATERMARK": "0", "WHISPER_DEVICE": "cpu", "WHISPER_COMPUTE": "int8"})
        if pipeline_api_key:
            environment["GEMINI_API_KEY"] = pipeline_api_key
        log = (directory / "worker.log").open("ab")
        try:
            process = self._popen([sys.executable, str(self.worker_path)],
                                  cwd=str(self.worker_path.parent), env=environment,
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        except Exception:
            log.close()
            state.update({"status": "error", "mensaje": "No se pudo reanudar el procesamiento de bloques",
                          "ended_at": time.time()})
            write_state(directory, state)
            raise
        log.close()
        with self._lock:
            self._processes[session_id] = process
            if getattr(process, "pid", None):
                state["worker_pid"] = int(process.pid)
                state["worker_proc_start"] = _proc_start_time(int(process.pid))
            write_state(directory, state)
        if self.auth_checker and state.get("auth_type"):
            threading.Thread(target=self._monitor_auth, args=(session_id,),
                             name=f"live-auth-{session_id[:8]}", daemon=True).start()
        return state


class LiveSessionRuntime:
    """Capture, analyze, queue and render one live session in its worker."""
    def __init__(self, session_id: str, url: str, output_dir: str | Path, stop_file: str | Path):
        self.session_id, self.url = session_id, url
        self.output_dir = Path(output_dir)
        self.stop_file = Path(stop_file)
        self.segment_dir = self.output_dir / "segments"
        self.work_dir = self.output_dir / ".live_work"
        self.state_lock = threading.RLock()
        self._last_saved_at = 0.0
        self.state = read_state(self.output_dir) or {
            "id": session_id, "url": url, "clips": [], "candidates": [], "notices": [],
            "segments": 0, "rtf": None,
        }
        try:
            self.min_clip_seconds, self.max_clip_seconds = validate_clip_duration_range(
                self.state.get("min_clip_seconds", DEFAULT_CLIP_MIN_SECONDS),
                self.state.get("max_clip_seconds", DEFAULT_CLIP_MAX_SECONDS))
        except ValueError:
            self.min_clip_seconds = DEFAULT_CLIP_MIN_SECONDS
            self.max_clip_seconds = DEFAULT_CLIP_MAX_SECONDS
        self.state.setdefault("min_clip_seconds", self.min_clip_seconds)
        self.state.setdefault("max_clip_seconds", self.max_clip_seconds)
        self.state.setdefault("segments_total", 0)
        self.state.setdefault("stats", {"detectados": 0, "descartados": 0,
                                         "errores": 0, "renderizados": 0,
                                         "picos_audio": 0, "palabras_clave": 0,
                                         "rechazos": {}})
        _ensure_capture_fields(self.state)
        self.state.update({"status": "iniciando", "updated_at": time.time()})
        self.stop_mode = None
        self._save()

    def _save(self, *, force: bool = False):
        with self.state_lock:
            now = time.time()
            if not force and now - self._last_saved_at < 1.0:
                return False
            self.state["updated_at"] = now
            write_state(self.output_dir, self.state)
            self._last_saved_at = now
            return True

    def _status(self, status, details=None):
        with self.state_lock:
            now = time.time()
            previous = self.state.get("status")
            self.state["status"] = status
            if status == "capturando" and self.state.get("capture_started_at") is None:
                self.state["capture_started_at"] = now
                self.state["capture_ended_at"] = None
                self.state["capture_elapsed_seconds"] = 0
            started_at = self.state.get("capture_started_at")
            if started_at is not None:
                ended_at = self.state.get("capture_ended_at")
                self.state["capture_elapsed_seconds"] = max(
                    0, int((float(ended_at) if ended_at is not None else now) - float(started_at)))
            if details:
                if status == "reconectando":
                    if previous != status:
                        self.state["reconnections"] = int(self.state.get("reconnections", 0)) + 1
                        self._activity_locked("reconectando", "Se perdió la conexión; intentando reconectar")
                elif status == "error" and details.get("error"):
                    self.state["mensaje"] = details["error"]
                    if previous != status:
                        self._activity_locked("error_captura", details["error"])
                elif details.get("title"):
                    self.state["titulo"] = details["title"]
            if status == "capturando" and previous != status:
                self._activity_locked("captura_conectada", "Conexión con el directo establecida")
            elif status == "detenido" and previous != status:
                self._activity_locked("captura_detenida", "Captura detenida")
            self._save(force=True)

    def _capture_ended(self):
        with self.state_lock:
            if self.state.get("capture_started_at") is None:
                return
            if self.state.get("capture_ended_at") is None:
                _finish_capture_fields(self.state, time.time())
                self._save(force=True)

    def _activity_locked(self, kind: str, text: str, **details):
        notices = self.state.setdefault("notices", [])
        notices.append({"tipo": kind, "mensaje": str(text), "at": time.time(), **details})
        self.state["notices"] = notices[-50:]

    def _notice(self, text: str, kind: str = "info", **details):
        with self.state_lock:
            self._activity_locked(kind, text, **details)
            self._save(force=True)

    def _sync_queue(self, work_queue, *, force: bool = False):
        states = work_queue.snapshot()["states"]
        with self.state_lock:
            previous = {str(item.get("id")): item for item in self.state.get("queue", [])}
            changed = force or self.state.get("queue", []) != states
            for item in states:
                old = previous.get(str(item.get("id")), {})
                if item.get("status") == "renderizando" and old.get("status") != "renderizando":
                    number = str(item.get("id", "")).rsplit("_", 1)[-1].lstrip("0") or "1"
                    self._activity_locked("render_iniciado", f"Comenzó el procesamiento del clip {number}",
                                          clip_id=str(item.get("id")))
                    changed = True
            if changed:
                self.state["queue"] = states
                by_id = {str(item.get("id")): item for item in states}
                for candidate in self.state.get("candidates", []):
                    queue_item = by_id.get(str(candidate.get("id")))
                    if queue_item:
                        candidate["status"] = queue_item.get("status", candidate.get("status"))
                        if queue_item.get("finished_at"):
                            candidate["finished_at"] = queue_item["finished_at"]
                _trim_candidate_history(self.state)
                self._save(force=True)

    def _queue_phase(self, work_queue, candidate_id: str, phase: str):
        updated = work_queue.set_phase(candidate_id, phase)
        with self.state_lock:
            previous = next((item for item in self.state.get("queue", [])
                             if str(item.get("id")) == str(candidate_id)), {})
            states = work_queue.snapshot()["states"]
            changed = self.state.get("queue", []) != states
            if previous.get("phase") != phase:
                number = str(candidate_id).rsplit("_", 1)[-1].lstrip("0") or "1"
                self._activity_locked("fase_clip", f"Clip {number}: {phase.replace('_', ' ')}",
                                      clip_id=str(candidate_id), phase=phase)
                changed = True
            if changed:
                self.state["queue"] = states
                self._save(force=True)
        return updated

    def _stop_requested(self):
        try:
            return self.stop_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def _run_block_mode(self):
        """Capture continuously while a separate thread runs full-pipeline blocks."""
        import csv
        import json
        import queue
        import shutil
        import subprocess
        from .blocks import (BlockManager, block_pipeline_command, build_block_timeline,
                             _terminate_process_group, clip_overlaps_prior, map_mp4_range)
        from .child_env import child_env
        from .config import (BLOCK_FILLER_SCORE, BLOCK_MIN_PARTIAL_MINUTES,
                             BLOCK_MAX_PENDING, BLOCK_OVERLAP_SECONDS,
                             CRITICAL_FREE_GB, MIN_FREE_GB)
        from .recorder import StreamRecorder
        from .resolver import resolve_live

        block_minutes = int(self.state.get("block_minutes", BLOCK_MINUTES))
        block_seconds = block_minutes * 60
        resume_only = os.environ.get("LIVE_RESUME_BLOCKS") == "1"
        manager = BlockManager(self.output_dir, block_minutes=block_minutes,
                               overlap_seconds=BLOCK_OVERLAP_SECONDS)
        self.segment_dir.mkdir(parents=True, exist_ok=True)
        blocks_dir = self.output_dir / "blocks"
        blocks_dir.mkdir(parents=True, exist_ok=True)
        work_queue = queue.Queue()
        cancel_processing = threading.Event()
        session_zero = time.monotonic()
        run_marks = {}
        segment_records = {}
        csv_readers = {}
        current_index = 0
        if not resume_only:
            manager.open_block(0, 0, block_seconds)

        def elapsed():
            return max(0.0, time.monotonic() - session_zero)

        def on_run_start(first_index, started_at):
            start_s = max(0.0, started_at - session_zero)
            run_marks[int(first_index)] = start_s
            manager.register_run(first_index, start_s)

        def read_segment_csvs():
            for list_path in sorted(self.segment_dir.glob("segments_*.csv")):
                reader = csv_readers.setdefault(list_path, {"pos": 0, "pending": b"", "duration": 0.0})
                try:
                    size = list_path.stat().st_size
                    if size < reader["pos"]:
                        reader.update({"pos": 0, "pending": b"", "duration": 0.0})
                    if size == reader["pos"]:
                        continue
                    with list_path.open("rb") as handle:
                        handle.seek(reader["pos"])
                        data = reader["pending"] + handle.read()
                    reader["pos"] = size
                    complete_end = data.rfind(b"\n") + 1
                    complete, reader["pending"] = data[:complete_end], data[complete_end:]
                    try:
                        first_index = int(list_path.stem.rsplit("_", 1)[-1])
                        run_start = manager.state.get("runs", {}).get(str(first_index),
                                                                       run_marks.get(first_index, 0.0))
                    except ValueError:
                        run_start = 0.0
                    for line in complete.splitlines():
                        try:
                            row = next(csv.reader([line.decode("utf-8")]))
                            if len(row) < 3:
                                continue
                            media = Path(row[0].strip().strip('"'))
                            if not media.is_absolute():
                                media = list_path.parent / media
                            index = int(media.stem.rsplit("_", 1)[-1])
                            run_offset = float(row[1].strip().strip('"'))
                            duration = max(0.0, float(row[2].strip().strip('"')) - run_offset)
                            record = {"index": index, "name": media.name, "path": str(media),
                                      "session_start_s": run_start + reader["duration"],
                                      "duration_s": duration}
                        except (UnicodeDecodeError, csv.Error, ValueError, IndexError):
                            continue
                        segment_records[index] = record
                        reader["duration"] += duration
                        if current_index in {item["index"] for item in manager.state["blocks"]}:
                            active = next((item for item in manager.state["blocks"]
                                           if item["index"] == current_index), None)
                            if active and record["session_start_s"] + duration > max(
                                    0.0, active["start_s"] - (BLOCK_OVERLAP_SECONDS if current_index else 0)):
                                manager.register_segment(active["id"], media.name)
                except OSError:
                    continue

        def process_block(block):
            block_id = block["id"]
            started = time.monotonic()
            attempt_no = int(block.get("attempts", 0)) + 1
            output_dir = blocks_dir / f"{int(block['index']):03d}" / f"attempt_{attempt_no:02d}"
            output_dir.mkdir(parents=True, exist_ok=True)
            source = output_dir / f"bloque_{int(block['index']):03d}.mp4"
            try:
                pause_notified = False
                while shutil.disk_usage(self.output_dir).free < MIN_FREE_GB * (1024 ** 3):
                    if not pause_notified:
                        self._notice(f"Procesamiento pausado: se requieren {MIN_FREE_GB:g} GB libres",
                                     "aviso")
                        pause_notified = True
                    if cancel_processing.is_set() or self._stop_requested() == "detener_ya":
                        manager.set_phase(block_id, "en_cola", error="Procesamiento cancelado; se conservan los segmentos")
                        return
                    time.sleep(5)
                inputs = []
                for entry in block.get("timeline", []):
                    for name in entry.get("segments", []):
                        candidate = (self.segment_dir / Path(name).name).resolve()
                        if self.segment_dir.resolve() not in candidate.parents or not candidate.is_file():
                            raise RuntimeError(f"Falta el segmento {Path(name).name}")
                        inputs.append(candidate)
                if not inputs:
                    manager.set_phase(block_id, "error", error="El bloque no tiene segmentos válidos")
                    return
                concat_file = output_dir / "concat.txt"
                concat_file.write_text("".join(
                    "file '" + str(path).replace("'", "'\\''") + "'\n" for path in inputs),
                    encoding="utf-8")
                assembled = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                     "-safe", "0", "-i", str(concat_file), "-c", "copy", "-bsf:a",
                     "aac_adtstoasc", str(source)], capture_output=True, text=True, timeout=1800)
                if assembled.returncode:
                    assembled = subprocess.run(
                        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                         "-safe", "0", "-i", str(concat_file), "-c", "copy", str(source)],
                        capture_output=True, text=True, timeout=1800)
                if assembled.returncode:
                    raise RuntimeError("No se pudo ensamblar el bloque con ffmpeg")
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                        "format=duration:stream=codec_type", "-of", "json", str(source)],
                                       capture_output=True, text=True, timeout=60)
                if probe.returncode:
                    raise RuntimeError("ffprobe no pudo validar el bloque")
                probe_data = json.loads(probe.stdout or "{}")
                actual_duration = float((probe_data.get("format") or {}).get("duration") or 0)
                expected_duration = sum(float(item["duration_s"]) for item in block.get("timeline", []))
                stream_types = {item.get("codec_type") for item in probe_data.get("streams", [])}
                if (not actual_duration or "video" not in stream_types or "audio" not in stream_types
                        or abs(actual_duration - expected_duration) > max(1.0, expected_duration * .03)):
                    raise RuntimeError("La duración o las pistas del bloque no pasaron la validación")
                manager.set_phase(block_id, "transcribiendo", video_path=str(source), progress=5,
                                  attempts=attempt_no)
                main_py = Path(__file__).resolve().parents[1] / "main.py"
                env = child_env()
                pending_count = sum(item.get("phase") in {"cerrado", "en_cola", "transcribiendo",
                                                           "seleccionando", "renderizando", "error"}
                                    for item in manager.state["blocks"])
                clip_min = max(1, int(os.environ.get("LIVE_BLOCK_MIN_CLIPS", "5")))
                clip_max = max(clip_min, int(os.environ.get("LIVE_BLOCK_CLIP_TARGET_MAX", "8")))
                reductions = max(0, pending_count - BLOCK_MAX_PENDING)
                effective_max = max(clip_min, clip_max - reductions)
                whisper_model = os.environ.get("LIVE_WHISPER_MODEL", "small")
                degraded = None
                if effective_max == clip_min and pending_count > BLOCK_MAX_PENDING + (clip_max - clip_min):
                    whisper_model = "base"
                    degraded = "whisper_base"
                elif pending_count > BLOCK_MAX_PENDING:
                    degraded = "menos_clips_por_bloque"
                with self.state_lock:
                    if self.state.get("block_degradation") != degraded:
                        self.state["block_degradation"] = degraded
                        self._activity_locked("backpressure",
                                              "Carga alta: se redujo temporalmente el máximo de clips por bloque"
                                              if degraded == "menos_clips_por_bloque" else
                                              "Carga alta: Whisper usa el modelo base temporalmente"
                                              if degraded == "whisper_base" else
                                              "La cola de bloques volvió a su configuración normal")
                        self._save(force=True)
                env.update({"AUTO_HOOK": "1", "CLIP_TARGET_MIN": str(clip_min),
                            "CLIP_TARGET_MAX": str(effective_max), "WHISPER_MODEL": whisper_model,
                            "CLIP_MIN_SECONDS": str(self.min_clip_seconds),
                            "CLIP_MAX_SECONDS": str(self.max_clip_seconds),
                            "SOURCE_CAP_MINUTES": str((expected_duration + 1) / 60),
                            "CLIP_WORKERS": "1", "WATERMARK": "0"})
                env.pop("MAX_SOURCE_MINUTES", None)
                log_path = output_dir / "pipeline.log"
                manager.set_phase(block_id, "transcribiendo", progress=10)
                with log_path.open("ab") as log:
                    process = subprocess.Popen(block_pipeline_command(main_py, source, output_dir, env=env),
                                               cwd=str(main_py.parent), env=env, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=subprocess.STDOUT,
                                               start_new_session=True)
                    try:
                        timeout = max(1, int(os.environ.get("LIVE_BLOCK_TIMEOUT_SECONDS", "21600")))
                    except ValueError:
                        timeout = 21600
                    deadline = time.monotonic() + timeout
                    while process.poll() is None:
                        if cancel_processing.is_set() or self._stop_requested() == "detener_ya":
                            _terminate_process_group(process)
                            raise RuntimeError("Procesamiento cancelado; se conservan los segmentos")
                        stages_path = output_dir / "stages.json"
                        try:
                            stage_data = json.loads(stages_path.read_text(encoding="utf-8"))
                            stage_name = stage_data.get("current_stage")
                            counters = stage_data.get("counters") or {}
                        except (OSError, ValueError):
                            stage_name = None
                            counters = {}
                        phase_by_stage = {"transcription": "transcribiendo", "clip_selection": "seleccionando",
                                          "cut_and_reframe": "renderizando", "hooks": "renderizando",
                                          "subtitles": "renderizando"}
                        mapped_phase = phase_by_stage.get(stage_name)
                        if mapped_phase:
                            current = manager.get(block_id)
                            clip_total = int(counters.get("total", 0))
                            clip_ready = int(counters.get("ready", 0))
                            progress = min(99, int(clip_ready / max(1, clip_total) * 100)) if clip_total else current.get("progress", 0)
                            if (current.get("phase") != mapped_phase or current.get("progress") != progress
                                    or current.get("clips_processed") != clip_ready
                                    or current.get("clips_total") != clip_total):
                                manager.set_phase(block_id, mapped_phase, progress=progress,
                                                  clips_processed=clip_ready, clips_total=clip_total)
                        if time.monotonic() >= deadline:
                            _terminate_process_group(process)
                            raise TimeoutError("Se agotó el tiempo de procesamiento del bloque")
                        time.sleep(1)
                if process.returncode != 0:
                    raise RuntimeError(f"main.py terminó con código {process.returncode}; consulte el registro del bloque")
                metadata_files = sorted(output_dir.glob("*_metadata.json"), key=lambda path: path.stat().st_mtime)
                if not metadata_files:
                    raise RuntimeError("main.py terminó sin generar metadatos")
                metadata = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
                saved_clips = []
                existing = [clip for item in manager.state["blocks"] if item["index"] < block["index"]
                            for clip in item.get("clips", []) if clip.get("status") == "completado"]
                for index, raw_clip in enumerate(metadata.get("shorts", []), start=1):
                    try:
                        interval = map_mp4_range(block.get("timeline", []), raw_clip["start"], raw_clip["end"])
                    except ValueError as exc:
                        saved_clips.append({**raw_clip, "status": "cruza_hueco", "block_id": block_id})
                        continue
                    duplicate = clip_overlaps_prior(interval["start_s"], interval["end_s"], existing)
                    filename = f"block_{int(block['index']) + 1:03d}_clip_{index:02d}.mp4"
                    rendered_candidates = [path for path in output_dir.glob(f"*_clip_{index}.mp4")
                                           if not path.name.startswith("temp_")]
                    rendered = max(rendered_candidates, key=lambda path: path.stat().st_mtime,
                                   default=None)
                    if duplicate:
                        saved_clips.append({**raw_clip, **interval, "status": "duplicado", "block_id": block_id})
                        continue
                    if not rendered:
                        saved_clips.append({**raw_clip, **interval, "status": "candidato_sin_renderizar", "block_id": block_id})
                        continue
                    shutil.copy2(rendered, self.output_dir / filename)
                    clip = {key: raw_clip.get(key) for key in (
                        "video_description_for_tiktok", "video_description_for_instagram",
                        "video_title_for_youtube_short", "viral_hook_text", "predicted_score")}
                    clip.update({"id": f"{block_id}_{index}", "block_id": block_id,
                                 "file": filename, "start": interval["start_s"], "end": interval["end_s"],
                                 "video_url": f"/videos/{self.session_id}/{filename}",
                                 "metadata_source": "ai" if raw_clip.get("viral_hook_text") else "fallback",
                                 "relleno": float(raw_clip.get("predicted_score") or 100) < BLOCK_FILLER_SCORE,
                                 "status": "completado"})
                    saved_clips.append(clip)
                    existing.append(clip)
                manager.set_phase(block_id, "completado", clips=saved_clips, progress=100,
                                  video_path=None, duration_processing_s=time.monotonic() - started,
                                  error=None)
                manager.release_segments(block_id)
                source.unlink(missing_ok=True)
                with self.state_lock:
                    self.state.setdefault("clips", []).extend(item for item in saved_clips
                                                               if item.get("status") == "completado")
                    self.state["blocks_summary"] = manager.summary()
                    self._save(force=True)
            except Exception as exc:
                phase = "en_cola" if cancel_processing.is_set() or self._stop_requested() == "detener_ya" else "error"
                manager.set_phase(block_id, phase, error=str(exc)[:300],
                                  duration_processing_s=time.monotonic() - started)
                with self.state_lock:
                    stats = self.state.setdefault("stats", {})
                    stats["errores"] = int(stats.get("errores", 0)) + 1
                    self.state["blocks_summary"] = manager.summary()
                    self._activity_locked("error_bloque", f"No se pudo procesar el bloque {block['index'] + 1}")
                    self._save(force=True)

        def process_loop():
            queued_ids = set()
            while True:
                try:
                    block = work_queue.get(timeout=1)
                except queue.Empty:
                    manager.reload()
                    if cancel_processing.is_set():
                        continue
                    block = next((item for item in manager.state["blocks"]
                                  if item.get("phase") in {"cerrado", "en_cola"}
                                  and item.get("id") not in queued_ids), None)
                    if block is None:
                        continue
                    queued_ids.add(block["id"])
                try:
                    if block is None:
                        return
                    manager.reload()
                    current_block = manager.get(block["id"])
                    if current_block.get("phase") in {"cerrado", "en_cola"}:
                        block = current_block
                        block["phase"] = "en_cola"
                        manager.save()
                        process_block(block)
                except Exception as exc:
                    with self.state_lock:
                        self.state.setdefault("stats", {})["errores"] = int(self.state["stats"].get("errores", 0)) + 1
                        self._activity_locked("error_bloque", f"Error inesperado del trabajador de bloques: {type(exc).__name__}")
                        self._save(force=True)
                finally:
                    if block is not None:
                        queued_ids.discard(block.get("id"))
                        work_queue.task_done()

        if resume_only:
            read_segment_csvs()
            for saved in list(manager.state["blocks"]):
                if saved.get("phase") == "cerrado" and not saved.get("timeline"):
                    timeline, gaps = build_block_timeline(
                        list(segment_records.values()), saved["start_s"], saved["end_s"],
                        BLOCK_OVERLAP_SECONDS if int(saved.get("index", 0)) else 0)
                    if timeline:
                        manager.close_block(saved["id"], timeline, gaps)
                    else:
                        manager.set_phase(saved["id"], "omitido",
                                          error="El bloque recuperado no conserva segmentos válidos")
        processor = threading.Thread(target=process_loop, name="live-block-worker", daemon=True)
        processor.start()
        if resume_only:
            with self.state_lock:
                self.state.update({"status": "finalizando", "mensaje": "Procesando bloques guardados"})
                self._save(force=True)
            while True:
                requested = self._stop_requested()
                if requested == "detener_ya":
                    cancel_processing.set()
                    break
                manager.reload()
                phases = {item.get("phase") for item in manager.state["blocks"]}
                if not phases.intersection({"cerrado", "en_cola", "transcribiendo",
                                            "seleccionando", "renderizando", "error"}):
                    break
                if requested == "terminar_pendientes" and not phases.intersection(
                        {"cerrado", "en_cola", "transcribiendo", "seleccionando", "renderizando"}):
                    break
                time.sleep(1)
            work_queue.join()
            work_queue.put(None)
            processor.join()
            with self.state_lock:
                self.state["blocks_summary"] = manager.summary()
                self.state.update({"status": "detenido", "ended_at": time.time()})
                self._save(force=True)
            return
        recorder = StreamRecorder(self.segment_dir)
        self._status("iniciando")
        recorder.supervise(self.url, resolve=resolve_live,
                           on_state=lambda state, details: self._status(state, details),
                           on_run_start=on_run_start, on_capture_end=self._capture_ended)
        finalized = False
        try:
            while True:
                requested = self._stop_requested()
                capture_done = not recorder._supervisor_thread.is_alive()
                free_gb = shutil.disk_usage(self.output_dir).free / (1024 ** 3)
                if not capture_done and free_gb < CRITICAL_FREE_GB:
                    self._notice("Captura detenida: el disco alcanzó el nivel crítico. Los bloques quedan conservados.",
                                 "error")
                    recorder.stop_supervisor()
                    capture_done = True
                    with self.state_lock:
                        self.state["status"] = "detenido_por_disco"
                        self.state["mensaje"] = "Captura detenida por falta crítica de espacio"
                        self._save(force=True)
                if requested:
                    self.stop_mode = requested
                    self._status("finalizando" if requested == "terminar_pendientes" else "deteniendo")
                    recorder.stop_supervisor()
                    capture_done = True
                    if requested == "detener_ya":
                        cancel_processing.set()
                read_segment_csvs()
                now = elapsed()
                next_index = int(now // block_seconds)
                closed_blocks = []
                while current_index < next_index:
                    old = next((item for item in manager.state["blocks"] if item["index"] == current_index), None)
                    if old and old["phase"] == "grabando":
                        timeline, gaps = build_block_timeline(list(segment_records.values()),
                                                              old["start_s"], old["end_s"],
                                                              BLOCK_OVERLAP_SECONDS if current_index else 0)
                        closed = manager.close_block(old["id"], timeline, gaps)
                        if closed["phase"] == "cerrado":
                            closed_blocks.append(closed)
                    current_index += 1
                    next_block = manager.open_block(current_index, current_index * block_seconds,
                                                    (current_index + 1) * block_seconds)
                    for record in segment_records.values():
                        if record["session_start_s"] + record["duration_s"] > max(
                                0.0, next_block["start_s"] - BLOCK_OVERLAP_SECONDS):
                            manager.register_segment(next_block["id"], record["name"])
                for closed in closed_blocks:
                    work_queue.put(closed)
                with self.state_lock:
                    self.state["blocks_summary"] = manager.summary()
                    self.state["segments_total"] = len(segment_records)
                    pending_count = int(self.state["blocks_summary"]["pendientes"])
                    if pending_count <= BLOCK_MAX_PENDING and self.state.get("block_degradation"):
                        self.state["block_degradation"] = None
                        self._activity_locked("backpressure", "La cola de bloques volvió a su configuración normal")
                    self._save()
                if capture_done:
                    if not finalized:
                        active_block = manager.get(next((item["id"] for item in manager.state["blocks"]
                                                         if item["index"] == current_index)))
                        partial = min(now, active_block["end_s"]) - active_block["start_s"]
                        threshold = BLOCK_MIN_PARTIAL_MINUTES * 60
                        if partial >= threshold:
                            timeline, gaps = build_block_timeline(list(segment_records.values()),
                                                                  active_block["start_s"], now,
                                                                  BLOCK_OVERLAP_SECONDS if current_index else 0)
                            closed = manager.close_block(active_block["id"], timeline, gaps)
                            if closed["phase"] == "cerrado":
                                work_queue.put(closed)
                        elif active_block["phase"] == "grabando":
                            manager.set_phase(active_block["id"], "omitido",
                                              error="El bloque parcial no alcanzó la duración mínima")
                            manager.release_segments(active_block["id"])
                            self._notice(
                                f"El bloque parcial se omitió porque duró menos de {BLOCK_MIN_PARTIAL_MINUTES} minutos",
                                "aviso")
                        finalized = True
                    manager.reload()
                    pending = [item for item in manager.state["blocks"]
                               if item.get("phase") in {"cerrado", "en_cola", "transcribiendo",
                                                         "seleccionando", "renderizando", "error"}]
                    if self.stop_mode == "detener_ya":
                        work_queue.join()
                        work_queue.put(None)
                        processor.join()
                        with self.state_lock:
                            self.state.update({"status": "detenido", "ended_at": time.time()})
                            self.state["blocks_summary"] = manager.summary()
                            self._save(force=True)
                        break
                    pending_count = sum(item.get("phase") in {"cerrado", "en_cola", "transcribiendo",
                                                               "seleccionando", "renderizando", "error"}
                                        for item in manager.state["blocks"])
                    if pending_count <= BLOCK_MAX_PENDING:
                        with self.state_lock:
                            if self.state.get("block_degradation"):
                                self.state["block_degradation"] = None
                                self._activity_locked("backpressure", "La cola de bloques volvió a su configuración normal")
                                self._save(force=True)
                    if not pending:
                        work_queue.put(None)
                        processor.join()
                        break
                    if self.state.get("status") != "detenido_por_disco":
                        self._status("finalizando", {"title": self.state.get("titulo")})
                time.sleep(1)
            with self.state_lock:
                self.state["blocks_summary"] = manager.summary()
                self.state["status"] = "detenido"
                self.state["ended_at"] = time.time()
                self._save(force=True)
        except Exception as exc:
            cancel_processing.set()
            recorder.stop_supervisor()
            self._capture_ended()
            with self.state_lock:
                self.state.update({"status": "error", "mensaje": str(exc)[:300], "ended_at": time.time()})
                self.state.setdefault("stats", {})["errores"] = int(self.state["stats"].get("errores", 0)) + 1
                self._save(force=True)
            raise

    def _render_worker(self, work_queue, buffer, render_gate, render_stop, transcript_store,
                       transcript_lock):
        attempts = 0
        while True:
            try:
                self._render_worker_loop(work_queue, buffer, render_gate, render_stop,
                                         transcript_store, transcript_lock)
                return
            except Exception as exc:
                attempts += 1
                self._notice(f"El worker de render tuvo un fallo: {type(exc).__name__}", "error",
                             render_worker_restart=attempts)
                if attempts >= 3:
                    with self.state_lock:
                        self.state["render_worker_status"] = "error"
                        stats = self.state.setdefault("stats", {})
                        stats["errores"] = int(stats.get("errores", 0)) + 1
                        self._save(force=True)
                    return
                time.sleep(0.5 * attempts)

    def _render_worker_loop(self, work_queue, buffer, render_gate, render_stop, transcript_store,
                            transcript_lock):
        from .clipper import render_candidate
        from .window import build_source_window
        index = len(self.state.get("clips", []))
        while True:
            if not render_gate.wait(render_stop):
                return
            item = work_queue.get(timeout=0.5)
            if item is None:
                if work_queue.snapshot()["queue_size"] == 0 and work_queue._closed:
                    return
                continue
            candidate_id = str(item.get("id"))
            window_path = None
            try:
                self._sync_queue(work_queue)
                self._queue_phase(work_queue, candidate_id, "preparando_ventana")
                window = build_source_window(buffer, item, self.work_dir)
                window_path = Path(window["path"])
                local_candidate = dict(item)
                local_candidate["start"] = window["start"]
                local_candidate["end"] = window["end"]
                with transcript_lock:
                    transcript = transcript_store.snapshot(
                        window["offset"], window["offset"] + window["actual_duration"])
                local_transcript = {"text": "", "language": transcript.get("language", ""), "segments": []}
                for segment in transcript.get("segments", []):
                    start, end = float(segment["start"]), float(segment["end"])
                    if end < window["offset"] or start > window["offset"] + window["actual_duration"]:
                        continue
                    words = [{**word, "start": max(0.0, float(word["start"]) - window["offset"]),
                              "end": max(0.0, float(word["end"]) - window["offset"])}
                             for word in segment.get("words", [])
                             if float(word["end"]) >= window["offset"]
                             and float(word["start"]) <= window["offset"] + window["actual_duration"]]
                    local_transcript["segments"].append({
                        "start": max(0.0, start - window["offset"]),
                        "end": max(0.0, end - window["offset"]),
                        "text": segment.get("text", ""), "words": words})
                result = render_candidate(window["path"], local_candidate, local_transcript,
                                          self.output_dir, index,
                                          on_phase=lambda name: self._queue_phase(work_queue, candidate_id, name))
                index += 1
                if not Path(result["path"]).is_file():
                    raise RuntimeError("No se encontró el archivo final del clip")
                clip = result["clip"]
                clip["start"], clip["end"] = item["start"], item["end"]
                clip["source_window_id"] = item.get("id", candidate_id)
                clip["video_url"] = f"/videos/{self.session_id}/{clip['file']}"
                work_queue.complete(candidate_id, ready=True)
                self._notice(f"Clip {index + 1} terminado", "clip_completado", clip_id=candidate_id)
                with self.state_lock:
                    self.state.setdefault("clips", []).append(clip)
                    self.state.setdefault("stats", {}).setdefault("renderizados", 0)
                    self.state["stats"]["renderizados"] += 1
                    self.state.setdefault("candidates", [])
                    self.state["queue"] = work_queue.snapshot()["states"]
                    _trim_candidate_history(self.state)
                    write_state(self.output_dir, self.state)
                print(f"CLIP_READY {index - 1} {clip['file']}", flush=True)
            except Exception as exc:
                work_queue.complete(candidate_id, ready=False, error=str(exc)[:300])
                with self.state_lock:
                    stats = self.state.setdefault("stats", {})
                    stats["errores"] = int(stats.get("errores", 0)) + 1
                    _trim_candidate_history(self.state)
                self._notice(f"No se pudo renderizar el clip: {type(exc).__name__}", "error",
                             clip_id=candidate_id)
            finally:
                if window_path:
                    window_path.unlink(missing_ok=True)
                with transcript_lock:
                    transcript_store.unpin(candidate_id)
                self._sync_queue(work_queue)

    def run(self):
        if self.state.get("mode") == "blocks":
            return self._run_block_mode()
        from .asr import IncrementalTranscriber
        from .audio import aggregate_buckets, extract_wav, extract_wav_window, rms_db_buckets
        from .buffer import SegmentBuffer
        from .config import BUFFER_MINUTES, TRANSCRIPT_KEEP_SECONDS
        from .detector import LiveDetector
        from .judge import judge_candidate
        from .queue import LiveWorkQueue, RenderPriorityGate
        from .recorder import StreamRecorder
        from .resolver import resolve_live
        from .transcript import RollingTranscript
        from .window import select_window_segments

        self.segment_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        buffer = SegmentBuffer(self.segment_dir, retention_seconds=BUFFER_MINUTES * 60)
        work_queue = LiveWorkQueue(buffer=buffer)
        render_gate = RenderPriorityGate()
        render_stop = threading.Event()
        detector = LiveDetector(min_seconds=self.min_clip_seconds,
                                max_seconds=self.max_clip_seconds)
        transcriber = IncrementalTranscriber()
        transcript_store = RollingTranscript()
        transcript_lock = threading.Lock()

        renderer = threading.Thread(target=self._render_worker,
                                    args=(work_queue, buffer, render_gate, render_stop,
                                          transcript_store, transcript_lock),
                                    name="live-render", daemon=True)
        renderer.start()
        judge_jobs = __import__("queue").Queue()
        judge_stop = object()

        def judge_loop():
            while True:
                job = judge_jobs.get()
                candidate = None
                try:
                    if job is judge_stop:
                        return
                    candidate, transcript_copy = job
                    with self.state_lock:
                        for item in self.state.setdefault("candidates", []):
                            if str(item.get("id")) == str(candidate.get("id")):
                                item["status"] = "evaluando"
                                item["evaluating_started_at"] = time.time()
                                break
                        self._activity_locked("evaluacion_iniciada", "Evaluando el momento destacado",
                                              clip_id=str(candidate.get("id")))
                        self._save(force=True)
                    judged = judge_candidate(candidate, transcript_copy)
                    judged["id"] = candidate["id"]
                    entries = buffer.retained()
                    selected = select_window_segments(entries, max(0.0, candidate["start"] - 10),
                                                      candidate["end"] + 10)
                    previous_queue = {str(item.get("id")): item.get("status")
                                      for item in work_queue.snapshot()["states"]}
                    queue_state = work_queue.offer(judged,
                                                   segment_indices=[item.index for item in selected])
                    queue_snapshot = work_queue.snapshot()
                    new_discards = sum(
                        1 for item in queue_snapshot["states"]
                        if item.get("status") == "descartado_por_saturacion"
                        and previous_queue.get(str(item.get("id"))) != "descartado_por_saturacion")
                    with transcript_lock:
                        for record in queue_snapshot["states"]:
                            if record.get("status") not in {"en_cola", "renderizando"}:
                                transcript_store.unpin(record.get("id"))
                        if queue_state.get("status") != "en_cola":
                            transcript_store.unpin(candidate["id"])
                    with self.state_lock:
                        candidates = self.state.setdefault("candidates", [])
                        detected = next((item for item in candidates
                                         if str(item.get("id")) == str(candidate.get("id"))), {})
                        detected_at = detected.get("detected_at", time.time())
                        replacement = {**detected, **judged, "status": queue_state["status"],
                                       "detected_at": detected_at, "evaluated_at": time.time()}
                        self.state["candidates"] = [
                            replacement if str(item.get("id")) == str(candidate.get("id")) else item
                            for item in candidates]
                        stats = self.state.setdefault("stats", {})
                        stats["descartados"] = int(stats.get("descartados", 0)) + new_discards
                        _trim_candidate_history(self.state)
                        self.state["queue"] = work_queue.snapshot()["states"]
                        if queue_state["status"] == "en_cola":
                            self._activity_locked("clip_en_cola", "Momento destacado añadido a la cola",
                                                  clip_id=str(candidate.get("id")))
                        else:
                            self._activity_locked("clip_descartado", "Clip descartado: la cola alcanzó su límite",
                                                  clip_id=str(candidate.get("id")),
                                                  reason=queue_state.get("reason"))
                        self._save(force=True)
                except Exception as exc:
                    if candidate:
                        with transcript_lock:
                            transcript_store.unpin(candidate["id"])
                        with self.state_lock:
                            stats = self.state.setdefault("stats", {})
                            stats["errores"] = int(stats.get("errores", 0)) + 1
                            for item in self.state.setdefault("candidates", []):
                                if str(item.get("id")) == str(candidate.get("id")):
                                    item.update({"status": "error", "error": str(exc)[:300],
                                                 "finished_at": time.time()})
                            _trim_candidate_history(self.state)
                            self._activity_locked("error_clip", "No se pudo evaluar el momento destacado",
                                                  clip_id=str(candidate.get("id")))
                            self._save(force=True)
                    self._notice(f"No se pudo evaluar un candidato: {type(exc).__name__}", "error")
                finally:
                    judge_jobs.task_done()

        judge_thread = threading.Thread(target=judge_loop, name="live-judge", daemon=True)
        judge_thread.start()
        recorder = StreamRecorder(self.segment_dir)
        self._status("iniciando")
        recorder.supervise(self.url, resolve=resolve_live,
                           on_state=lambda state, details: self._status(state, details),
                           on_capture_end=self._capture_ended)
        processed = set()
        buckets_since_detection = []
        next_asr_start = 0.0
        try:
            while True:
                requested = self._stop_requested()
                capture_done = not recorder._supervisor_thread.is_alive()
                if requested:
                    self.stop_mode = requested
                    self._status("deteniendo" if requested == "detener_ya" else "finalizando")
                    recorder.stop_supervisor()
                    if requested == "detener_ya":
                        work_queue.discard_pending()
                        render_stop.set()
                        work_queue.close()
                        self._notice("Sesión detenida inmediatamente", "info")
                        with self.state_lock:
                            self.state["queue"] = work_queue.snapshot()["states"]
                            self.state.update({"status": "detenido", "ended_at": time.time()})
                            self._save(force=True)
                        if os.name == "posix":
                            time.sleep(0.2)
                            os.killpg(os.getpgrp(), signal.SIGTERM)
                        break
                    capture_done = True
                entries = buffer.refresh()
                new_entries = [entry for entry in entries if entry.index not in processed and entry.path.exists()]
                for entry in new_entries:
                    processed.add(entry.index)
                    wav = self.work_dir / f"audio_{entry.index:06d}.wav"
                    try:
                        extract_wav(entry.path, wav)
                        buckets = rms_db_buckets(wav)
                        for item in buckets:
                            item["start"] += entry.start
                            item["end"] += entry.start
                        buckets_since_detection.extend(aggregate_buckets(buckets, 5))
                    except Exception as exc:
                        self._notice("El segmento no tiene audio utilizable", "aviso")
                    finally:
                        wav.unlink(missing_ok=True)
                    with self.state_lock:
                        self.state["segments_total"] = int(self.state.get("segments_total") or 0) + 1
                        if self.state.get("segments") != len(entries):
                            self.state["segments"] = len(entries)
                        self._save()

                latest = max((entry.end for entry in entries), default=0.0)
                while latest >= next_asr_start + transcriber.block_seconds:
                    selected = select_window_segments(entries, next_asr_start,
                                                      next_asr_start + transcriber.block_seconds)
                    local_start = max(0.0, next_asr_start - selected[0].start)
                    wav = self.work_dir / f"asr_{int(next_asr_start):08d}.wav"
                    try:
                        extract_wav_window([entry.path for entry in selected], wav,
                                           start=local_start, duration=transcriber.block_seconds)
                        result = transcriber.transcribe_block(wav, session_start=next_asr_start,
                                                              audio_duration=transcriber.block_seconds)
                        transcript_store.language = result.get("language") or transcript_store.language
                        with transcript_lock:
                            for segment in result.get("segments", []):
                                transcript_store.add_words(segment.get("words", []))
                        if result.get("notice"):
                            self._notice(result["notice"], "aviso")
                        if not transcriber._asr_enabled:
                            asr_status = "detenido_por_carga"
                        elif result.get("notice"):
                            asr_status = "degradado"
                        else:
                            asr_status = "activo"
                        if not transcriber._asr_enabled:
                            paused = render_gate.release_for_asr_disabled()
                        else:
                            paused = (render_gate.update_asr_rtf(result["rtf"])
                                      if result.get("rtf") is not None else render_gate.paused)
                        if paused != self.state.get("render_priority_paused", False):
                            work_queue.set_wait_reason("prioridad_de_captura" if paused else None)
                            with self.state_lock:
                                self.state["render_priority_paused"] = paused
                                self._activity_locked(
                                    "prioridad_captura",
                                    "Renderizado pausado temporalmente para proteger captura y transcripción"
                                    if paused else "Se reanudó el renderizado después de estabilizar la transcripción")
                                self.state["queue"] = work_queue.snapshot()["states"]
                                self._save()
                        with self.state_lock:
                            changed = (self.state.get("rtf") != result.get("rtf")
                                       or self.state.get("asr_status") != asr_status)
                            self.state["rtf"] = result.get("rtf")
                            self.state["asr_status"] = asr_status
                            if changed:
                                self._save()
                        next_asr_start += transcriber.block_seconds - 2
                    except Exception as exc:
                        with self.state_lock:
                            self.state["asr_status"] = "no_disponible"
                            stats = self.state.setdefault("stats", {})
                            stats["bloques_asr_fallidos"] = int(stats.get("bloques_asr_fallidos", 0)) + 1
                        self._notice(f"Transcripción en vivo no disponible: {type(exc).__name__}", "aviso")
                        next_asr_start += transcriber.block_seconds - 2
                    finally:
                        wav.unlink(missing_ok=True)

                if buckets_since_detection:
                    candidates = detector.detect(buckets_since_detection, transcript_store, latest_time=latest)
                    buckets_since_detection = []
                    metrics = detector.last_metrics
                    with self.state_lock:
                        stats = self.state.setdefault("stats", {})
                        for key, source in (("picos_audio", "audio_peaks"),
                                            ("palabras_clave", "keyword_hits")):
                            stats[key] = int(stats.get(key, 0)) + int(metrics.get(source, 0))
                        rejects = stats.setdefault("rechazos", {})
                        for key in ("rejected_weak_signal", "rejected_cooldown",
                                    "rejected_bounds", "rejected_overlap"):
                            rejects[key] = int(rejects.get(key, 0)) + int(metrics.get(key, 0))
                        stats["pendientes"] = int(metrics.get("pending", 0))
                        self._save()
                    for candidate in candidates:
                        with self.state_lock:
                            detected_at = time.time()
                            stats = self.state.setdefault("stats", {})
                            stats["detectados"] = int(stats.get("detectados", 0)) + 1
                            self.state.setdefault("candidates", []).append({**candidate, "status": "detectado",
                                                                             "detected_at": detected_at})
                            self._activity_locked("momento_detectado",
                                                  f"Momento destacado detectado: {candidate.get('why') or 'señales de audio/transcripción'}",
                                                  clip_id=str(candidate.get("id")))
                            self._save()
                        with transcript_lock:
                            transcript_store.pin(candidate["id"], max(0.0, candidate["start"] - 20),
                                                 candidate["end"] + 20)
                            candidate_transcript = transcript_store.snapshot(
                                max(0.0, candidate["start"] - 20), candidate["end"] + 20)
                        judge_jobs.put((candidate, candidate_transcript))
                buffer.prune(entries)
                first_retained = next((entry.start for entry in entries if entry.path.exists()), None)
                keep_from = (first_retained if first_retained is not None
                             else latest - TRANSCRIPT_KEEP_SECONDS) - 15
                with transcript_lock:
                    transcript_store.prune(keep_from)
                if capture_done:
                    if render_gate.paused:
                        render_gate.resume_for_shutdown()
                        work_queue.set_wait_reason(None)
                        with self.state_lock:
                            self.state["render_priority_paused"] = False
                            self.state["queue"] = work_queue.snapshot()["states"]
                            self._activity_locked(
                                "prioridad_captura",
                                "Se liberó la pausa de render para terminar los clips pendientes")
                            self._save()
                    break
                time.sleep(1)

            pending_highlights = detector.discard_pending()
            if pending_highlights:
                self._notice(
                    f"Se descartaron {pending_highlights} momentos porque no había suficiente material "
                    f"para generar clips de al menos {self.min_clip_seconds} segundos.", "aviso")
            if self.stop_mode != "detener_ya":
                judge_jobs.join()
                judge_jobs.put(judge_stop)
                judge_thread.join(timeout=10)
                work_queue.close()
                renderer.join()
                if self.state.get("status") != "error":
                    self._status("detenido")
                    with self.state_lock:
                        self.state["ended_at"] = time.time()
                        self._save()
        except Exception as exc:
            recorder.stop_supervisor()
            self._capture_ended()
            self._notice(f"La sesión terminó por un error: {type(exc).__name__}", "error")
            with self.state_lock:
                self.state.update({"status": "error", "mensaje": str(exc)[:300], "ended_at": time.time()})
                self._save(force=True)
            try:
                work_queue.close()
            except Exception:
                pass
            raise
        finally:
            transcriber.close()
