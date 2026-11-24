import subprocess
from pathlib import Path

import pytest

from live.buffer import Segment
from live.judge import judge_candidate
from live.queue import LiveWorkQueue, RenderPriorityGate
from live.window import build_source_window, select_window_segments, translate_words_to_window


class FakeBuffer:
    def __init__(self):
        self.pinned = set()
        self.segments = [Segment(i, f"seg_{i:06d}.ts", i * 10.0, 10.0) for i in range(8)]

    def refresh(self):
        return self.segments

    def pin(self, indices):
        self.pinned.update(indices)

    def unpin(self, indices):
        self.pinned.difference_update(indices)


def test_bounded_queue_replaces_lowest_score_and_unpins():
    buffer = FakeBuffer()
    queue = LiveWorkQueue(max_queue=2, buffer=buffer)
    queue.offer({"id": "a", "predicted_score": 10}, segment_indices=[1])
    queue.offer({"id": "b", "predicted_score": 20}, segment_indices=[2])
    result = queue.offer({"id": "c", "predicted_score": 30}, segment_indices=[3])

    assert result["status"] == "en_cola"
    assert buffer.pinned == {2, 3}
    assert queue.snapshot()["queue_size"] == 2
    selected = queue.get(timeout=0.1)
    assert selected["id"] == "c"
    queue.complete("c")
    assert 3 not in buffer.pinned


def test_judged_candidates_keep_distinct_queue_ids():
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("LLM no disponible")

    queue = LiveWorkQueue(max_queue=3)
    transcript = {"text": "Hola mundo", "language": "es", "segments": []}
    candidates = [
        {"id": "live_000101", "start": 100, "end": 130, "signals": [], "why": "uno"},
        {"id": "live_000102", "start": 140, "end": 170, "signals": [], "why": "dos"},
    ]

    for candidate in candidates:
        judged = judge_candidate(candidate, transcript, generate=unavailable)
        assert judged["id"] == candidate["id"]
        queue.offer(judged)

    snapshot = queue.snapshot()
    assert snapshot["queue_size"] == 2
    assert {item["id"] for item in snapshot["states"]} == {item["id"] for item in candidates}


def test_queue_persists_wait_and_render_phase_transitions():
    queue = LiveWorkQueue(max_queue=2)
    queued = queue.offer({"id": "live_000001", "predicted_score": 70, "start": 12, "end": 42})
    assert queued["status"] == "en_cola"
    assert queued["queued_at"] <= queued["updated_at"]
    assert queued["wait_reason"] == "esperando_capacidad"

    item = queue.get(timeout=0.1)
    assert item["id"] == "live_000001"
    started = queue.snapshot()["states"][0]
    assert started["status"] == "renderizando"
    assert started["started_at"]
    assert started["phase"] == "preparando_ventana"

    queue.set_phase(item["id"], "cortando_fragmento")
    phase_state = queue.snapshot()["states"][0]
    unchanged = queue.set_phase(item["id"], "cortando_fragmento")
    assert unchanged["updated_at"] == phase_state["updated_at"]
    assert [entry["phase"] for entry in unchanged["phase_history"]] == [
        "preparando_ventana", "cortando_fragmento"]
    queue.complete(item["id"], ready=False, error="ffmpeg falló")
    failed = queue.snapshot()["states"][0]
    assert failed["status"] == "error"
    assert failed["failed_phase"] == "cortando_fragmento"
    assert failed["finished_at"] >= failed["started_at"]


def test_render_gate_sets_wait_reason_for_queued_work():
    queue = LiveWorkQueue(max_queue=2)
    queue.offer({"id": "live_000001", "predicted_score": 50})
    queue.set_wait_reason("prioridad_de_captura")
    assert queue.snapshot()["states"][0]["wait_reason"] == "prioridad_de_captura"


def test_render_gate_pauses_only_after_sustained_slow_asr():
    gate = RenderPriorityGate(threshold=0.8, samples=3)
    assert gate.update_asr_rtf(0.9) is False
    assert gate.update_asr_rtf(0.9) is False
    assert gate.update_asr_rtf(0.9) is True
    assert gate.update_asr_rtf(0.2) is False
    assert gate.wait()


def test_render_gate_can_release_pending_work_after_capture_ends():
    gate = RenderPriorityGate(threshold=0.8, samples=1)
    assert gate.update_asr_rtf(1.0) is True
    gate.resume_for_shutdown()
    assert gate.wait()


def test_window_selects_required_segments_and_translates_words(tmp_path):
    buffer = FakeBuffer()
    selected = select_window_segments(buffer.refresh(), 12, 42)
    assert [item.index for item in selected] == [1, 2, 3, 4]
    wordset = translate_words_to_window([
        {"word": " hello", "start": 15.0, "end": 15.5},
        {"word": " old", "start": 1.0, "end": 1.5},
    ], offset=12, start=12, end=42)
    assert wordset == [{"word": " hello", "start": 3.0, "end": 3.5}]

    def runner(command, **kwargs):
        assert kwargs["check"] is True
        open(command[-1], "wb").write(b"window")

    result = build_source_window(buffer, {"id": "clip1", "start": 12, "end": 42},
                                 tmp_path, margin=10, runner=runner)
    assert result["offset"] == 2
    assert result["start"] == 10
    assert result["end"] == 40
    assert result["segment_indices"] == [0, 1, 2, 3, 4, 5]
    assert result["path"].endswith("clip1_window.ts")


@pytest.mark.parametrize("minimum,maximum", [(10, 30), (30, 60), (60, 120), (120, 240)])
def test_source_window_accepts_each_configured_duration_range(tmp_path, minimum, maximum):
    class LongBuffer(FakeBuffer):
        def __init__(self):
            self.pinned = set()
            self.segments = [Segment(i, f"long_{i:06d}.ts", i * 10.0, 10.0)
                             for i in range(30)]

    start = 100.0
    candidate = {"id": f"range_{minimum}", "start": start, "end": start + minimum,
                 "min_clip_seconds": minimum, "max_clip_seconds": maximum}

    result = build_source_window(LongBuffer(), candidate, tmp_path,
                                 runner=lambda command, **_kwargs: Path(command[-1]).write_bytes(b"window"))

    assert result["end"] - result["start"] == minimum
    assert result["segment_indices"]


def test_source_window_rejects_candidate_outside_retained_buffer(tmp_path):
    class TruncatedBuffer(FakeBuffer):
        def __init__(self):
            self.pinned = set()
            self.segments = [Segment(i, f"late_{i:06d}.ts", 20 + i * 10.0, 10.0)
                             for i in range(5)]

    with pytest.raises(ValueError, match="No hay suficiente material"):
        build_source_window(TruncatedBuffer(), {"id": "too_early", "start": 5, "end": 35,
                                                "min_clip_seconds": 30, "max_clip_seconds": 60},
                           tmp_path)
