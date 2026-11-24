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
                     validate_clip_duration_range)


_SESSION_ID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$", re.I)
_TERMINAL = {"detenido", "error"}
_ACTIVE = {"iniciando", "esperando", "capturando", "reconectando", "deteniendo", "finalizando"}


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


def _write_state_unlocked(directory: Path, state: dict) -> None:
    target = directory / "live_state.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    if state.get("clips"):
        metadata = directory / "live_metadata.json"
        temporary_metadata = metadata.with_suffix(".tmp")
        temporary_metadata.write_text(json.dumps({"shorts": state["clips"]},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_metadata, metadata)


def write_state(directory: str | Path, state: dict) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with _state_file_lock(directory):
        existing = read_state(directory)
        if existing:
            existing_clips = existing.get("clips", [])
            clips = state.get("clips", [])
            editable = ("video_title_for_youtube_short", "video_description_for_tiktok",
                        "video_description_for_instagram", "viral_hook_text")
            for index, old_clip in enumerate(existing_clips):
                if index < len(clips) and old_clip.get("metadata_edited_at"):
                    for key in editable:
                        if key in old_clip:
                            clips[index][key] = old_clip[key]
                    clips[index]["metadata_edited_at"] = old_clip["metadata_edited_at"]
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
               max_clip_seconds: int = DEFAULT_CLIP_MAX_SECONDS) -> dict:
        with self._create_lock:
            return self._create_unlocked(url, user_id=user_id, auth_context=auth_context,
                                          min_clip_seconds=min_clip_seconds,
                                          max_clip_seconds=max_clip_seconds)

    def _create_unlocked(self, url: str, *, user_id=None, auth_context: dict | None = None,
               min_clip_seconds: int = DEFAULT_CLIP_MIN_SECONDS,
               max_clip_seconds: int = DEFAULT_CLIP_MAX_SECONDS) -> dict:
        min_clip_seconds, max_clip_seconds = validate_clip_duration_range(
            min_clip_seconds, max_clip_seconds)
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
                 "capture_started_at": None, "capture_ended_at": None,
                 "capture_elapsed_seconds": 0,
                 "auth_type": (auth_context or {}).get("type"),
                 "auth_expires_at": (auth_context or {}).get("expires_at"),
                 "auth_session_ref": (auth_context or {}).get("session_ref"),
                 "auth_status": "valid" if auth_context else "unmanaged"}
        write_state(directory, state)
        environment = os.environ.copy()
        environment.update({"LIVE_SESSION_ID": session_id, "LIVE_URL": url,
                            "LIVE_OUTPUT_DIR": str(directory),
                            "LIVE_STOP_FILE": str(directory / "stop.request"),
                            "LIVE_CLIP_MIN": str(min_clip_seconds),
                            "LIVE_CLIP_MAX": str(max_clip_seconds),
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


class LiveSessionRuntime:
    """Capture, analyze, queue and render one live session in its worker."""
    def __init__(self, session_id: str, url: str, output_dir: str | Path, stop_file: str | Path):
        self.session_id, self.url = session_id, url
        self.output_dir = Path(output_dir)
        self.stop_file = Path(stop_file)
        self.segment_dir = self.output_dir / "segments"
        self.work_dir = self.output_dir / ".live_work"
        self.state_lock = threading.RLock()
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
        _ensure_capture_fields(self.state)
        self.state.update({"status": "iniciando", "updated_at": time.time()})
        self.stop_mode = None
        self._save()

    def _save(self):
        with self.state_lock:
            self.state["updated_at"] = time.time()
            write_state(self.output_dir, self.state)

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
            self._save()

    def _capture_ended(self):
        with self.state_lock:
            if self.state.get("capture_started_at") is None:
                return
            if self.state.get("capture_ended_at") is None:
                _finish_capture_fields(self.state, time.time())
                self._save()

    def _activity_locked(self, kind: str, text: str, **details):
        notices = self.state.setdefault("notices", [])
        notices.append({"tipo": kind, "mensaje": str(text), "at": time.time(), **details})
        self.state["notices"] = notices[-50:]

    def _notice(self, text: str, kind: str = "info", **details):
        with self.state_lock:
            self._activity_locked(kind, text, **details)
            self._save()

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
                self._save()

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
                self._save()
        return updated

    def _stop_requested(self):
        try:
            return self.stop_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def _render_worker(self, work_queue, buffer, render_gate, render_stop, transcript_store,
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
                    self.state.setdefault("candidates", [])
                    self.state["queue"] = work_queue.snapshot()["states"]
                    write_state(self.output_dir, self.state)
                print(f"CLIP_READY {index - 1} {clip['file']}", flush=True)
            except Exception as exc:
                work_queue.complete(candidate_id, ready=False, error=str(exc)[:300])
                self._notice(f"No se pudo renderizar el clip: {type(exc).__name__}", "error",
                             clip_id=candidate_id)
            finally:
                if window_path:
                    window_path.unlink(missing_ok=True)
                with transcript_lock:
                    transcript_store.unpin(candidate_id)
                self._sync_queue(work_queue)

    def run(self):
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
                        self._save()
                    judged = judge_candidate(candidate, transcript_copy)
                    judged["id"] = candidate["id"]
                    entries = buffer.retained()
                    selected = select_window_segments(entries, max(0.0, candidate["start"] - 10),
                                                      candidate["end"] + 10)
                    queue_state = work_queue.offer(judged,
                                                   segment_indices=[item.index for item in selected])
                    queue_snapshot = work_queue.snapshot()
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
                        self.state["queue"] = work_queue.snapshot()["states"]
                        if queue_state["status"] == "en_cola":
                            self._activity_locked("clip_en_cola", "Momento destacado añadido a la cola",
                                                  clip_id=str(candidate.get("id")))
                        else:
                            self._activity_locked("clip_descartado", "Clip descartado: la cola alcanzó su límite",
                                                  clip_id=str(candidate.get("id")),
                                                  reason=queue_state.get("reason"))
                        self._save()
                except Exception as exc:
                    if candidate:
                        with transcript_lock:
                            transcript_store.unpin(candidate["id"])
                        with self.state_lock:
                            for item in self.state.setdefault("candidates", []):
                                if str(item.get("id")) == str(candidate.get("id")):
                                    item.update({"status": "error", "error": str(exc)[:300],
                                                 "finished_at": time.time()})
                            self._activity_locked("error_clip", "No se pudo evaluar el momento destacado",
                                                  clip_id=str(candidate.get("id")))
                            self._save()
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
                            self._save()
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
                        if result.get("notice") and "detenido por carga" in result["notice"].lower():
                            asr_status = "detenido_por_carga"
                        elif result.get("notice"):
                            asr_status = "degradado"
                        else:
                            asr_status = "activo"
                        paused = render_gate.update_asr_rtf(result["rtf"]) if result.get("rtf") is not None else render_gate.paused
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
                        self._notice(f"Transcripción en vivo no disponible: {type(exc).__name__}", "aviso")
                        next_asr_start += transcriber.block_seconds - 2
                    finally:
                        wav.unlink(missing_ok=True)

                if buckets_since_detection:
                    candidates = detector.detect(buckets_since_detection, transcript_store, latest_time=latest)
                    buckets_since_detection = []
                    for candidate in candidates:
                        with self.state_lock:
                            detected_at = time.time()
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
                self._save()
            try:
                work_queue.close()
            except Exception:
                pass
            raise
        finally:
            transcriber.close()
