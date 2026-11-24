import os
import threading
import time

import pytest

from live.buffer import SegmentBuffer
from live.recorder import StreamRecorder
import live.resolver as resolver


def test_resolver_uses_youtube_policy_and_returns_live_media(monkeypatch):
    class FakeYdl:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download=False):
            assert download is False
            assert self.options["noplaylist"] is True
            return {
                "id": "live-id", "title": "Directo", "channel": "Canal",
                "is_live": True, "live_status": "is_live",
                "formats": [
                    {"url": "https://cdn.example/video", "height": 720,
                     "vcodec": "h264", "acodec": "none"},
                    {"url": "https://cdn.example/audio", "vcodec": "none",
                     "acodec": "aac", "abr": 128},
                ],
            }

    monkeypatch.setattr(resolver, "_attempts", lambda: [(None, False)])
    monkeypatch.setattr(resolver, "assert_public_url", lambda _url: None)
    result = resolver.resolve_live("https://www.youtube.com/live/abc", ydl_factory=FakeYdl)

    assert result["state"] == "en_vivo"
    assert result["video_url"] == "https://cdn.example/video"
    assert result["audio_url"] == "https://cdn.example/audio"


def test_resolver_rejects_non_youtube_urls():
    with pytest.raises(resolver.LiveResolveError, match="YouTube"):
        resolver.resolve_live("https://example.com/live")


def test_resolver_reports_scheduled_stream(monkeypatch):
    class FakeYdl:
        def __init__(self, _options): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def extract_info(self, _url, download=False):
            return {"live_status": "is_upcoming", "title": "Luego", "id": "id"}

    monkeypatch.setattr(resolver, "_attempts", lambda: [(None, False)])
    monkeypatch.setattr(resolver, "assert_public_url", lambda _url: None)
    assert resolver.resolve_live("https://youtube.com/watch?v=abc", ydl_factory=FakeYdl)["state"] == "programado"


def test_recorder_notifies_supervisor_completion_when_capture_never_started(tmp_path):
    finalized = threading.Event()
    statuses = []
    recorder = StreamRecorder(tmp_path)

    thread = recorder.supervise(
        "https://youtube.com/live/example",
        resolve=lambda _url: {"state": "no_en_vivo"},
        on_state=lambda status, _details: statuses.append(status),
        on_capture_end=finalized.set,
    )
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert finalized.is_set()
    assert statuses == ["finalizando"]


def test_recorder_command_supports_split_audio_and_resume_number(tmp_path):
    recorder = StreamRecorder(tmp_path, segment_seconds=10)
    recorder.next_number = 12
    command = recorder.build_command("https://cdn.example/v", "https://cdn.example/a")

    assert command[command.index("-segment_start_number") + 1] == "12"
    maps = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "-map"]
    assert maps == ["0:v:0", "1:a:0"]
    assert command[-1].endswith("seg_%06d.ts")
    assert "-segment_list_type" in command


def test_supervisor_reconnects_with_new_segment_and_csv_numbers(tmp_path):
    launches = []
    recorder = StreamRecorder(tmp_path)

    class ExitedProcess:
        pid = -1

        def poll(self):
            return 1

    def popen(command, **_kwargs):
        launches.append(command)
        if len(launches) == 1:
            (tmp_path / "seg_000000.ts").write_bytes(b"segment")
            (tmp_path / "segments_000000.csv").write_text(
                "seg_000000.ts,0.000000,10.000000\n", encoding="utf-8")
        elif len(launches) == 2:
            recorder._stop_event.set()
        return ExitedProcess()

    recorder._popen = popen
    thread = recorder.supervise(
        "https://youtube.com/live/example",
        resolve=lambda _url: {"state": "en_vivo", "video_url": "https://cdn.example/live"},
        retry_min=0.1,
        retry_max=0.1,
    )
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert len(launches) == 2
    numbers = [command[command.index("-segment_start_number") + 1] for command in launches]
    csv_paths = [command[command.index("-segment_list") + 1] for command in launches]
    assert numbers == ["0", "1"]
    assert csv_paths[0] != csv_paths[1]


def test_buffer_reads_csv_and_retains_pinned_segments(tmp_path):
    first = tmp_path / "seg_000004.ts"
    second = tmp_path / "seg_000005.ts"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    old = time.time() - 100
    os.utime(first, (old, old))
    os.utime(second, (old, old))
    (tmp_path / "segments.csv").write_text(
        'seg_000004.ts,0.000000,10.000000\nseg_000005.ts,10.000000,20.000000\n',
        encoding="utf-8",
    )
    buffer = SegmentBuffer(tmp_path, retention_seconds=10)
    entries = buffer.refresh()

    assert [(entry.index, entry.start, entry.duration) for entry in entries] == [
        (4, 0.0, 10.0), (5, 10.0, 10.0)
    ]
    buffer.pin([5])
    assert buffer.prune(now=time.time()) == [first]
    assert not first.exists()
    assert second.exists()


def test_buffer_incrementally_reads_complete_rows_and_preserves_offsets(tmp_path):
    paths = [tmp_path / f"seg_{index:06d}.ts" for index in range(4)]
    for path in paths:
        path.write_bytes(b"x")
    csv_path = tmp_path / "segments_000000.csv"
    csv_path.write_text("seg_000000.ts,0,10\nseg_000001.ts,10,20\nseg_000002.ts,20,30",
                        encoding="utf-8")
    buffer = SegmentBuffer(tmp_path)

    first = buffer.refresh()
    assert [(item.index, item.start) for item in first] == [(0, 0), (1, 10)]
    with csv_path.open("a", encoding="utf-8") as file:
        file.write("\n")
    second = buffer.refresh()
    assert [(item.index, item.start) for item in second] == [(0, 0), (1, 10), (2, 20)]
    assert buffer.refresh() == second

    next_csv = tmp_path / "segments_000003.csv"
    next_csv.write_text("seg_000003.ts,0,10\n", encoding="utf-8")
    combined = buffer.refresh()
    assert [(item.index, item.start) for item in combined][-1] == (3, 30)
    assert buffer.latest_end == 40


def test_buffer_truncated_csv_reloads_without_moving_timeline_backwards(tmp_path):
    for index in range(3):
        (tmp_path / f"seg_{index:06d}.ts").write_bytes(b"x")
    csv_path = tmp_path / "segments_000000.csv"
    csv_path.write_text("seg_000000.ts,0,10\nseg_000001.ts,10,20\n", encoding="utf-8")
    buffer = SegmentBuffer(tmp_path)
    assert [item.start for item in buffer.refresh()] == [0, 10]

    csv_path.write_text("seg_000002.ts,0,10\n", encoding="utf-8")
    refreshed = buffer.refresh()

    assert [(item.index, item.start) for item in refreshed] == [(2, 20)]
    assert buffer.latest_end == 30


def test_buffer_pruning_keeps_absolute_offsets_and_stops_at_fresh_segment(tmp_path):
    paths = [tmp_path / f"seg_{index:06d}.ts" for index in range(3)]
    for path in paths:
        path.write_bytes(b"x")
    csv_path = tmp_path / "segments.csv"
    csv_path.write_text("".join(f"seg_{index:06d}.ts,{index * 10},{(index + 1) * 10}\n"
                                 for index in range(3)), encoding="utf-8")
    old = time.time() - 100
    os.utime(paths[0], (old, old))
    os.utime(paths[1], (old, old))
    buffer = SegmentBuffer(tmp_path, retention_seconds=10)
    entries = buffer.refresh()
    removed = buffer.prune(entries, now=time.time())

    assert removed == paths[:2]
    assert [(item.index, item.start) for item in buffer.retained()] == [(2, 20)]
    assert buffer.first_start == 20
