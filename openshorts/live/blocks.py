"""Persistent editorial blocks for full-pipeline processing of live capture."""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

TERMINAL_BLOCK_STATES = {"completado", "omitido", "descartado"}
ACTIVE_BLOCK_STATES = {"grabando", "cerrado", "en_cola", "transcribiendo",
                       "seleccionando", "renderizando", "error"}
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


@contextmanager
def _manifest_lock(path: Path):
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    lock.acquire()
    handle = path.with_suffix(".lock").open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
        lock.release()


def map_mp4_range(timeline: list[dict], start_s: float, end_s: float,
                  *, tolerance_s: float = 1.0) -> dict:
    """Map a block-local range to session time, rejecting ranges crossing gaps."""
    start_s, end_s = float(start_s), float(end_s)
    if end_s < start_s:
        raise ValueError("El final del clip precede a su inicio")
    entries = sorted(timeline, key=lambda entry: float(entry["mp4_start_s"]))
    covered = [entry for entry in entries
               if float(entry["mp4_start_s"]) < end_s
               and float(entry["mp4_start_s"]) + float(entry["duration_s"]) > start_s]
    if not covered:
        raise ValueError("El clip queda fuera de la línea de tiempo")
    first = covered[0]
    last = covered[-1]
    for left, right in zip(covered, covered[1:]):
        left_mp4_end = float(left["mp4_start_s"]) + float(left["duration_s"])
        right_session_start = float(right["session_start_s"])
        left_session_end = float(left["session_start_s"]) + float(left["duration_s"])
        if abs((right_session_start - left_session_end) -
               (float(right["mp4_start_s"]) - left_mp4_end)) > tolerance_s:
            raise ValueError("cruza_hueco")
    return {"start_s": float(first["session_start_s"]) + start_s - float(first["mp4_start_s"]),
            "end_s": float(last["session_start_s"]) + end_s - float(last["mp4_start_s"])}


def build_block_timeline(segments: list[dict], start_s: float, end_s: float,
                         overlap_seconds: int = 0) -> tuple[list[dict], list[dict]]:
    """Select segments for an editorial interval and describe gaps in session time."""
    start_s = max(0.0, float(start_s) - max(0, int(overlap_seconds)))
    chosen = sorted((item for item in segments
                     if float(item["session_start_s"]) < float(end_s)
                     and float(item["session_start_s"]) + float(item["duration_s"]) > start_s),
                    key=lambda item: (float(item["session_start_s"]), int(item.get("index", 0))))
    timeline, gaps = [], []
    mp4_at = 0.0
    for item in chosen:
        session_at = float(item["session_start_s"])
        duration = max(0.0, float(item["duration_s"]))
        if timeline:
            previous = timeline[-1]
            session_end = float(previous["session_start_s"]) + float(previous["duration_s"])
            gap = session_at - session_end
            if gap > 1.0:
                gaps.append({"at_session_s": session_end, "seconds": gap})
            elif gap < -1.0:
                # Ignore duplicate coverage at transport stream boundaries.
                session_at = session_end
        timeline.append({"mp4_start_s": mp4_at, "session_start_s": session_at,
                         "duration_s": duration, "segments": [str(item["name"])]})
        mp4_at += duration
    # Merge adjacent runs with no meaningful gap, preserving individual TS inputs.
    merged = []
    for entry in timeline:
        if merged:
            previous = merged[-1]
            session_end = float(previous["session_start_s"]) + float(previous["duration_s"])
            if abs(float(entry["session_start_s"]) - session_end) < 1.0:
                previous["duration_s"] += float(entry["duration_s"])
                previous["segments"].extend(entry["segments"])
                continue
        merged.append(entry)
    cursor = 0.0
    for entry in merged:
        entry["mp4_start_s"] = cursor
        cursor += float(entry["duration_s"])
    return merged, gaps


def block_pipeline_command(main_py: str | Path, source: str | Path,
                           output_dir: str | Path, *, env: dict | None = None) -> list[str]:
    """Build the normal main.py invocation, with a pytest-only process seam."""
    env = os.environ if env is None else env
    override = env.get("LIVE_BLOCK_PIPELINE_CMD") if env.get("PYTEST_CURRENT_TEST") else None
    prefix = shlex.split(override, posix=os.name != "nt") if override else [sys.executable, "-u", str(main_py)]
    if not prefix:
        raise ValueError("LIVE_BLOCK_PIPELINE_CMD no puede estar vacío")
    return [*prefix, "-i", str(source), "-o", str(output_dir), "--generation-mode", "smart"]


def clip_overlaps_prior(start_s: float, end_s: float, prior_clips: list[dict],
                        threshold: float = 0.30) -> bool:
    duration = max(1.0, float(end_s) - float(start_s))
    for item in prior_clips:
        prior_start, prior_end = float(item.get("start", 0)), float(item.get("end", 0))
        intersection = max(0.0, min(float(end_s), prior_end) - max(float(start_s), prior_start))
        if intersection / min(duration, max(1.0, prior_end - prior_start)) > threshold:
            return True
    return False


def _terminate_process_group(process) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


class BlockManager:
    """Atomic blocks.json store and segment ownership registry."""
    def __init__(self, session_dir: str | Path, *, block_minutes: int = 40,
                 overlap_seconds: int = 90, max_attempts: int = 2, recover: bool = True):
        self.session_dir = Path(session_dir)
        self.segment_dir = self.session_dir / "segments"
        self.path = self.session_dir / "blocks.json"
        self.block_seconds = max(1, int(block_minutes)) * 60
        self.overlap_seconds = max(0, int(overlap_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.state = self._load()
        self._snapshot = deepcopy(self.state)
        if recover:
            self._recover()

    def _load(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("blocks"), list):
                raise ValueError("invalid blocks manifest")
            return state
        except (OSError, ValueError):
            return {"version": 1, "blocks": [], "segments": {}, "runs": {}}

    def save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        with _manifest_lock(self.path):
            disk = self._load()
            base_blocks = {item["id"]: item for item in self._snapshot.get("blocks", [])}
            merged_blocks = {item["id"]: item for item in disk.get("blocks", [])}
            for local in self.state.get("blocks", []):
                block_id = local["id"]
                base = base_blocks.get(block_id, {})
                remote = merged_blocks.setdefault(block_id, {})
                for key, value in local.items():
                    if key not in base or base.get(key) != value:
                        remote[key] = deepcopy(value)
            disk["blocks"] = sorted(merged_blocks.values(), key=lambda item: item.get("index", 0))
            base_segments = self._snapshot.get("segments", {})
            for name, local in self.state.get("segments", {}).items():
                base_owners = set(base_segments.get(name, {}).get("owners", []))
                local_owners = set(local.get("owners", []))
                remote = disk.setdefault("segments", {}).setdefault(name, {"owners": []})
                remote_owners = set(remote.get("owners", []))
                remote_owners.update(local_owners - base_owners)
                remote_owners.difference_update(base_owners - local_owners)
                remote["owners"] = sorted(remote_owners)
            for name in set(base_segments) - set(self.state.get("segments", {})):
                if disk.get("segments", {}).get(name) == base_segments[name]:
                    disk["segments"].pop(name, None)
            disk.setdefault("runs", {}).update(self.state.get("runs", {}))
            disk["version"] = max(1, int(disk.get("version", 1)))
            temporary.write_text(json.dumps(disk, ensure_ascii=False, separators=(",", ":")),
                                 encoding="utf-8")
            os.replace(temporary, self.path)
            self.state = disk
            self._snapshot = deepcopy(disk)

    def _recover(self) -> None:
        changed = False
        for block in self.state["blocks"]:
            if block.get("phase") == "grabando":
                block["phase"] = "cerrado" if block.get("segments") else "omitido"
                block["error"] = "Captura interrumpida; bloque recuperado" if block["phase"] == "cerrado" else None
                changed = True
            elif block.get("phase") in {"transcribiendo", "seleccionando", "renderizando"}:
                block["attempts"] = int(block.get("attempts", 0)) + 1
                block["phase"] = "error" if block["attempts"] > self.max_attempts else "en_cola"
                block["error"] = "Se interrumpió el procesamiento; reintente el bloque" if block["phase"] == "error" else None
                changed = True
        if changed:
            self.save()

    def blocks(self, *, offset: int = 0, limit: int = 50) -> list[dict]:
        limit = min(100, max(1, int(limit)))
        return self.state["blocks"][max(0, int(offset)):max(0, int(offset)) + limit]

    def open_block(self, index: int, start_s: float, end_s: float) -> dict:
        existing = next((item for item in self.state["blocks"] if item.get("index") == index), None)
        if existing:
            return existing
        block = {"id": str(uuid.uuid4()), "index": int(index), "start_s": float(start_s),
                 "end_s": float(end_s), "segments": [], "timeline": [], "gaps": [],
                 "video_path": None, "phase": "grabando", "progress": 0,
                 "clips": [], "attempts": 0, "error": None,
                 "created_at": time.time(), "finished_at": None,
                 "duration_processing_s": None}
        self.state["blocks"].append(block)
        self.state["blocks"].sort(key=lambda item: item["index"])
        self.save()
        return self.get(block["id"])

    def close_block(self, block_id: str, timeline: list[dict], gaps: list[dict] | None = None) -> dict:
        block = self.get(block_id)
        block["timeline"] = list(timeline)
        block["gaps"] = list(gaps or [])
        block["overlap_s"] = (max(0.0, float(block["start_s"])
                                  - float(timeline[0]["session_start_s"]))
                              if timeline and int(block.get("index", 0)) > 0 else 0.0)
        block["segments"] = list(dict.fromkeys(str(segment) for item in timeline
                                                for segment in item.get("segments", [])))
        block["phase"] = "cerrado" if timeline else "omitido"
        for segment in block["segments"]:
            owners = self.state["segments"].setdefault(segment, {"owners": []}).setdefault("owners", [])
            if block_id not in owners:
                owners.append(block_id)
        self.save()
        return self.get(block_id)

    def register_segment(self, block_id: str, name: str) -> None:
        block = self.get(block_id)
        name = Path(name).name
        if name not in block["segments"]:
            block["segments"].append(name)
        owners = self.state["segments"].setdefault(name, {"owners": []}).setdefault("owners", [])
        if block_id not in owners:
            owners.append(block_id)
        self.save()

    def register_run(self, first_segment_index: int, session_start_s: float) -> None:
        self.state.setdefault("runs", {})[str(int(first_segment_index))] = float(session_start_s)
        self.save()

    def set_phase(self, block_id: str, phase: str, **updates) -> dict:
        block = self.get(block_id)
        block.update(updates)
        block["phase"] = phase
        if phase in TERMINAL_BLOCK_STATES:
            block["finished_at"] = time.time()
        self.save()
        return self.get(block_id)

    def get(self, block_id: str) -> dict:
        for block in self.state["blocks"]:
            if block.get("id") == block_id:
                return block
        raise KeyError(block_id)

    def retry(self, block_id: str) -> dict:
        block = self.get(block_id)
        if block.get("phase") != "error":
            raise ValueError("Solo se pueden reintentar bloques con error")
        block.update({"phase": "en_cola", "error": None})
        self.save()
        return self.get(block_id)

    def omit(self, block_id: str) -> dict:
        block = self.get(block_id)
        if block.get("phase") not in {"cerrado", "en_cola", "error"}:
            raise ValueError("Solo se pueden omitir bloques cerrados, en cola o con error")
        block.update({"phase": "omitido", "error": "Omitido por decisión del usuario",
                      "finished_at": time.time()})
        self.save()
        self.release_segments(block_id)
        return self.get(block_id)

    def reload(self) -> None:
        self.state = self._load()
        self._snapshot = deepcopy(self.state)

    def release_segments(self, block_id: str) -> list[Path]:
        """Release ownership idempotently and delete only unowned media files."""
        block = self.get(block_id)
        if block.get("phase") not in TERMINAL_BLOCK_STATES:
            return []
        released = []
        for name in block.get("segments", []):
            record = self.state["segments"].get(name, {})
            record["owners"] = [owner for owner in record.get("owners", []) if owner != block_id]
            if not record["owners"]:
                path = (self.segment_dir / Path(name).name).resolve()
                if self.segment_dir.resolve() in path.parents:
                    path.unlink(missing_ok=True)
                self.state["segments"].pop(name, None)
                released.append(path)
        self.save()
        return released

    def summary(self) -> dict:
        blocks = self.state["blocks"]
        return {"total": len(blocks), "pendientes": sum(item.get("phase") in
                {"cerrado", "en_cola", "transcribiendo", "seleccionando", "renderizando", "error"}
                for item in blocks), "completados": sum(item.get("phase") == "completado" for item in blocks)}
