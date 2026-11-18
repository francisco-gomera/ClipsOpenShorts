import os
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


def test_recorder_command_supports_split_audio_and_resume_number(tmp_path):
    recorder = StreamRecorder(tmp_path, segment_seconds=10)
    recorder.next_number = 12
    command = recorder.build_command("https://cdn.example/v", "https://cdn.example/a")

    assert command[command.index("-segment_start_number") + 1] == "12"
    maps = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "-map"]
    assert maps == ["0:v:0", "1:a:0"]
    assert command[-1].endswith("seg_%06d.ts")
    assert "-segment_list_type" in command


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
