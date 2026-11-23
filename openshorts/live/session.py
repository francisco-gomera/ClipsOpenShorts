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


class LiveSessionManager:
    """Launches one isolated live worker per session and recovers stale state."""
    def __init__(self, output_dir: str | Path, *, worker_path: str | Path | None = None,
                 popen=subprocess.Popen):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.worker_path = Path(worker_path or Path(__file__).resolve().parents[1] / "live_worker.py")
        self._popen = popen
        self._processes = {}
        self._lock = threading.RLock()
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
            if state and state.get("status") not in _TERMINAL:
                state.update({"status": "detenido", "mensaje": "Sesión detenida al reiniciar el servidor",
                              "ended_at": time.time()})
                write_state(directory, state)

    def create(self, url: str, *, user_id=None,
               min_clip_seconds: int = DEFAULT_CLIP_MIN_SECONDS,
               max_clip_seconds: int = DEFAULT_CLIP_MAX_SECONDS) -> dict:
        min_clip_seconds, max_clip_seconds = validate_clip_duration_range(
            min_clip_seconds, max_clip_seconds)
        session_id = str(uuid.uuid4())
        directory = self._directory(session_id)
        directory.mkdir(parents=True, exist_ok=False)
        if user_id is not None:
            (directory / ".owner").write_text(str(user_id), encoding="utf-8")
        state = {"id": session_id, "url": url, "status": "iniciando", "created_at": time.time(),
                 "updated_at": time.time(), "clips": [], "candidates": [], "queue": [],
                 "notices": [], "segments": 0, "rtf": None, "user_id": str(user_id) if user_id else None,
                 "min_clip_seconds": min_clip_seconds, "max_clip_seconds": max_clip_seconds}
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
        return state

    def get(self, session_id: str) -> dict | None:
        directory = self._directory(session_id)
        state = read_state(directory)
        if not state:
            return None
        with self._lock:
            process = self._processes.get(session_id)
        if process is not None and process.poll() is not None and state.get("status") not in _TERMINAL:
            state.update({"status": "error", "mensaje": "El proceso de live clipping terminó inesperadamente",
                          "ended_at": time.time()})
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

    def stop(self, session_id: str, mode: str = "terminar_pendientes") -> dict | None:
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
        self.state.update({"status": "iniciando", "updated_at": time.time()})
        self.stop_mode = None

    def _save(self):
        with self.state_lock:
            self.state["updated_at"] = time.time()
            write_state(self.output_dir, self.state)

    def _status(self, status, details=None):
        with self.state_lock:
            self.state["status"] = status
            if details:
                if status == "reconectando":
                    self.state.setdefault("notices", []).append({"tipo": status, **details})
                elif status == "error" and details.get("error"):
                    self.state["mensaje"] = details["error"]
                elif details.get("title"):
                    self.state["titulo"] = details["title"]
            self._save()

    def _notice(self, text: str, kind: str = "info"):
        with self.state_lock:
            notices = self.state.setdefault("notices", [])
            notices.append({"tipo": kind, "mensaje": str(text), "at": time.time()})
            self.state["notices"] = notices[-50:]
            self._save()

    def _stop_requested(self):
        try:
            return self.stop_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    @staticmethod
    def _merge_words(transcript_words, new_words):
        import re
        for word in new_words:
            norm = re.sub(r"\W+", "", str(word.get("word", "")).lower())
            key = (norm, round(float(word.get("start", 0)), 1))
            if norm and key not in transcript_words:
                transcript_words[key] = dict(word)

    @staticmethod
    def _transcript(words_by_key, language):
        words = sorted(words_by_key.values(), key=lambda item: (item["start"], item["end"]))
        text = "".join(str(item.get("word", "")) for item in words).strip()
        segments = []
        if words:
            segments.append({"start": words[0]["start"], "end": words[-1]["end"],
                             "text": text, "words": words})
        return {"text": text, "language": language or "", "segments": segments}

    def _render_worker(self, work_queue, buffer, render_gate, render_stop, transcript_getter):
        from .clipper import render_candidate
        from .window import build_source_window
        index = len(self.state.get("clips", []))
        while True:
            item = work_queue.get(timeout=0.5)
            if item is None:
                if work_queue.snapshot()["queue_size"] == 0 and work_queue._closed:
                    return
                continue
            candidate_id = str(item.get("id"))
            window_path = None
            try:
                if not render_gate.wait(render_stop):
                    work_queue.complete(candidate_id, ready=False, error="render cancelado")
                    continue
                with self.state_lock:
                    self.state["queue"] = work_queue.snapshot()["states"]
                    self._save()
                window = build_source_window(buffer, item, self.work_dir)
                window_path = Path(window["path"])
                local_candidate = dict(item)
                local_candidate["start"] = window["start"]
                local_candidate["end"] = window["end"]
                transcript = transcript_getter()
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
                                          self.output_dir, index)
                index += 1
                if not Path(result["path"]).is_file():
                    raise RuntimeError("No se encontró el archivo final del clip")
                clip = result["clip"]
                clip["start"], clip["end"] = item["start"], item["end"]
                clip["source_window_id"] = item.get("id", candidate_id)
                clip["video_url"] = f"/videos/{self.session_id}/{clip['file']}"
                with self.state_lock:
                    self.state.setdefault("clips", []).append(clip)
                    self.state.setdefault("candidates", [])
                    self.state["queue"] = work_queue.snapshot()["states"]
                    write_state(self.output_dir, self.state)
                work_queue.complete(candidate_id, ready=True)
                print(f"CLIP_READY {index - 1} {clip['file']}", flush=True)
            except Exception as exc:
                work_queue.complete(candidate_id, ready=False, error=str(exc)[:300])
                self._notice(f"No se pudo renderizar un clip: {type(exc).__name__}", "error")
            finally:
                if window_path:
                    window_path.unlink(missing_ok=True)
                with self.state_lock:
                    self.state["queue"] = work_queue.snapshot()["states"]
                    self._save()

    def run(self):
        from .asr import IncrementalTranscriber
        from .audio import aggregate_buckets, extract_wav, extract_wav_window, rms_db_buckets
        from .buffer import SegmentBuffer
        from .config import BUFFER_MINUTES
        from .detector import LiveDetector
        from .judge import judge_candidate
        from .queue import LiveWorkQueue, RenderPriorityGate
        from .recorder import StreamRecorder
        from .resolver import resolve_live
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
        transcript_words = {}
        language = ""
        transcript_lock = threading.Lock()

        def transcript_snapshot():
            with transcript_lock:
                return self._transcript(transcript_words, language)

        renderer = threading.Thread(target=self._render_worker,
                                    args=(work_queue, buffer, render_gate, render_stop, transcript_snapshot),
                                    name="live-render", daemon=True)
        renderer.start()
        judge_jobs = __import__("queue").Queue()
        judge_stop = object()

        def judge_loop():
            while True:
                job = judge_jobs.get()
                try:
                    if job is judge_stop:
                        return
                    candidate, transcript_copy = job
                    judged = judge_candidate(candidate, transcript_copy)
                    entries = buffer.refresh()
                    selected = select_window_segments(entries, max(0.0, candidate["start"] - 10),
                                                      candidate["end"] + 10)
                    queue_state = work_queue.offer(judged,
                                                   segment_indices=[item.index for item in selected])
                    with self.state_lock:
                        self.state.setdefault("queue", []).append(queue_state)
                        self._save()
                except Exception as exc:
                    self._notice(f"No se pudo evaluar un candidato: {type(exc).__name__}", "error")
                finally:
                    judge_jobs.task_done()

        judge_thread = threading.Thread(target=judge_loop, name="live-judge", daemon=True)
        judge_thread.start()
        recorder = StreamRecorder(self.segment_dir)
        self._status("iniciando")
        recorder.supervise(self.url, resolve=resolve_live,
                           on_state=lambda state, details: self._status(state, details))
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
                        language = result.get("language") or language
                        with transcript_lock:
                            for segment in result.get("segments", []):
                                self._merge_words(transcript_words, segment.get("words", []))
                        if result.get("notice"):
                            self._notice(result["notice"], "aviso")
                        with self.state_lock:
                            self.state["rtf"] = result.get("rtf")
                            self._save()
                        next_asr_start += transcriber.block_seconds - 2
                    except Exception as exc:
                        self._notice(f"Transcripción en vivo no disponible: {type(exc).__name__}", "aviso")
                        next_asr_start += transcriber.block_seconds - 2
                    finally:
                        wav.unlink(missing_ok=True)

                if buckets_since_detection:
                    transcript = transcript_snapshot()
                    candidates = detector.detect(buckets_since_detection, transcript, latest_time=latest)
                    buckets_since_detection = []
                    for candidate in candidates:
                        with self.state_lock:
                            self.state.setdefault("candidates", []).append({**candidate, "status": "evaluando"})
                            self._save()
                        judge_jobs.put((candidate, transcript))
                buffer.prune()
                with self.state_lock:
                    self.state["queue"] = work_queue.snapshot()["states"]
                    self._save()
                if capture_done:
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
