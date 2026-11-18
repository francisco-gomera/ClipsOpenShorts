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

    def _set_state(self, candidate, state, **extra):
        record = {**candidate, "status": state, "updated_at": time.time(), **extra}
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
            self._set_state(item, "renderizando")
            return item

    def complete(self, candidate_id: str, *, ready: bool = True, error: str | None = None):
        with self._condition:
            record = self._states.get(str(candidate_id), {"id": str(candidate_id)})
            state = "completado" if ready else "error"
            record = {**record, "status": state, "updated_at": time.time()}
            if error:
                record["error"] = error
            self._states[str(candidate_id)] = record
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
                self._set_state(item, "cancelado", reason="cola vaciada")
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
