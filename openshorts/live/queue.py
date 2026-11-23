"""A bounded, score-prioritized clip render queue and CPU priority gate."""
from __future__ import annotations

import threading
import time
from collections import deque

from .config import MAX_QUEUE


class LiveWorkQueue:
    def __init__(self, max_queue: int = MAX_QUEUE, *, buffer=None):
        self.max_queue = max(1, int(max_queue))
        self.buffer = buffer
        self._items: list[dict] = []
        self._states: dict[str, dict] = {}
        self._condition = threading.Condition()
        self._closed = False
        self._active_id: str | None = None
        self._wait_reason: str | None = None

    def _set_state(self, candidate, state, **extra):
        now = time.time()
        record = {key: value for key, value in candidate.items() if key != "_seq"}
        record.update({"status": state, "updated_at": now, **extra})
        if state == "en_cola":
            record.setdefault("queued_at", now)
            record.setdefault("wait_reason", self._wait_reason or
                              ("otro_clip_en_procesamiento" if self._active_id else "esperando_capacidad"))
        elif state == "renderizando":
            record.setdefault("started_at", now)
            record.setdefault("phase", "preparando_ventana")
            record.setdefault("phase_started_at", now)
            record["wait_reason"] = None
        elif state in {"completado", "error", "cancelado", "descartado_por_saturacion"}:
            record.setdefault("finished_at", now)
        self._states[str(candidate.get("id"))] = record
        return record

    def offer(self, candidate: dict, *, segment_indices=()) -> dict:
        """Queue a candidate or discard the lowest-scoring queued item."""
        candidate = dict(candidate)
        candidate["segment_indices"] = sorted(set(int(i) for i in segment_indices))
        with self._condition:
            if self._closed:
                return self._set_state(candidate, "descartado_por_saturacion", reason="cola cerrada")
            if len(self._items) >= self.max_queue:
                lowest = min(self._items, key=lambda item: (float(item.get("predicted_score", 0)), item["_seq"]))
                if float(candidate.get("predicted_score", 0)) <= float(lowest.get("predicted_score", 0)):
                    return self._set_state(candidate, "descartado_por_saturacion",
                                           reason="cola llena; menor puntuación")
                self._items.remove(lowest)
                self._unpin(lowest)
                self._set_state(lowest, "descartado_por_saturacion", reason="reemplazado por mayor puntuación")
            candidate["_seq"] = time.monotonic_ns()
            self._items.append(candidate)
            self._pin(candidate)
            record = self._set_state(candidate, "en_cola")
            self._condition.notify()
            return record

    def _pin(self, item):
        if self.buffer and item.get("segment_indices"):
            self.buffer.pin(item["segment_indices"])

    def _unpin(self, item):
        if self.buffer and item.get("segment_indices"):
            self.buffer.unpin(item["segment_indices"])

    def get(self, timeout: float | None = None) -> dict | None:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._items and not self._closed:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if not self._items:
                return None
            item = max(self._items, key=lambda value: (float(value.get("predicted_score", 0)), -value["_seq"]))
            self._items.remove(item)
            item = {key: value for key, value in item.items() if key != "_seq"}
            self._active_id = str(item.get("id"))
            self._set_state(item, "renderizando")
            self._update_wait_reasons()
            return item

    def _update_wait_reasons(self, reason: str | None = None):
        for item in self._items:
            candidate_id = str(item.get("id"))
            record = self._states.get(candidate_id, item)
            next_reason = reason or self._wait_reason or (
                "otro_clip_en_procesamiento" if self._active_id else "esperando_capacidad")
            if record.get("wait_reason") != next_reason:
                self._states[candidate_id] = {**record, "wait_reason": next_reason,
                                              "updated_at": time.time()}

    def set_phase(self, candidate_id: str, phase: str) -> dict:
        """Persist one real render phase transition for a queued candidate."""
        with self._condition:
            key = str(candidate_id)
            record = self._states.get(key, {"id": key})
            history = list(record.get("phase_history") or [])
            same_phase = record.get("phase") == str(phase)
            if same_phase and history and history[-1].get("phase") == phase:
                return dict(record)
            now = time.time()
            started_at = record.get("phase_started_at") if same_phase else now
            history.append({"phase": str(phase), "started_at": started_at or now})
            updated = {**record, "status": "renderizando", "phase": str(phase),
                       "phase_started_at": started_at or now, "phase_history": history,
                       "updated_at": now, "wait_reason": None}
            self._states[key] = updated
            return dict(updated)

    def set_wait_reason(self, reason: str | None):
        with self._condition:
            self._wait_reason = reason
            self._update_wait_reasons(reason)

    def complete(self, candidate_id: str, *, ready: bool = True, error: str | None = None,
                 cancelled: bool = False):
        with self._condition:
            record = self._states.get(str(candidate_id), {"id": str(candidate_id)})
            state = "completado" if ready else ("cancelado" if cancelled else "error")
            now = time.time()
            record = {**record, "status": state, "updated_at": now,
                      "finished_at": now, "wait_reason": None}
            if ready:
                record.update({"phase": "finalizado", "phase_started_at": now})
            elif not cancelled:
                record["failed_phase"] = record.get("phase")
                record["phase"] = "error"
            if error:
                record["error"] = error
            self._states[str(candidate_id)] = record
            if self._active_id == str(candidate_id):
                self._active_id = None
            self._update_wait_reasons()
            if self.buffer and record.get("segment_indices"):
                self.buffer.unpin(record["segment_indices"])
            self._condition.notify_all()
            return dict(record)

    def discard_pending(self) -> list[str]:
        with self._condition:
            ids = []
            for item in self._items:
                ids.append(str(item.get("id")))
                self._unpin(item)
                self._set_state(item, "cancelado", reason="cola vaciada", finished_at=time.time())
            self._items.clear()
            return ids

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def snapshot(self) -> dict:
        with self._condition:
            return {"queued": sorted((dict(item) for item in self._items),
                                      key=lambda item: -float(item.get("predicted_score", 0))),
                    "states": [dict(item) for item in self._states.values()],
                    "queue_size": len(self._items), "max_queue": self.max_queue}


class RenderPriorityGate:
    """Pause render work while a rolling Whisper RTF average is above 0.8."""
    def __init__(self, *, threshold: float = 0.8, samples: int = 3):
        self.threshold = float(threshold)
        self._rtfs = deque(maxlen=max(1, samples))
        self._condition = threading.Condition()
        self.paused = False

    def update_asr_rtf(self, rtf: float) -> bool:
        with self._condition:
            self._rtfs.append(max(0.0, float(rtf)))
            self.paused = len(self._rtfs) == self._rtfs.maxlen and sum(self._rtfs) / len(self._rtfs) > self.threshold
            if not self.paused:
                self._condition.notify_all()
            return self.paused

    def wait(self, stop_event=None, poll: float = 0.5) -> bool:
        with self._condition:
            while self.paused and not (stop_event and stop_event.is_set()):
                self._condition.wait(poll)
            return not (stop_event and stop_event.is_set())

    def resume_for_shutdown(self):
        """Drain pending clips after capture ends; no capture remains to protect."""
        with self._condition:
            self.paused = False
            self._condition.notify_all()
