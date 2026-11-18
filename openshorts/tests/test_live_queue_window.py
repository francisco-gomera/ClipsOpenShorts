import subprocess

from live.buffer import Segment
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


def test_render_gate_pauses_only_after_sustained_slow_asr():
    gate = RenderPriorityGate(threshold=0.8, samples=3)
    assert gate.update_asr_rtf(0.9) is False
    assert gate.update_asr_rtf(0.9) is False
    assert gate.update_asr_rtf(0.9) is True
    assert gate.update_asr_rtf(0.2) is False
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
