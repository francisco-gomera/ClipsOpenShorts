from pathlib import Path
import shutil
import subprocess

import pytest

from live.clipper import render_candidate


def test_clipper_reuses_pipeline_chain_and_writes_sidecars(tmp_path, monkeypatch):
    calls = []

    def cut(_source, target, _start, _end, _number):
        Path(target).write_bytes(b"cut")

    def render(_source, target, output_format, *, force_strategy=None, subtitle_band=None):
        assert output_format == "vertical"
        assert force_strategy is None
        Path(target).write_bytes(b"rendered")
        calls.append("render")
        return True

    def caption(path, _transcript, _start, _end, *, split_ranges=None,
                plan_only=False, mark=False):
        calls.append("caption_plan" if plan_only else "caption")
        if plan_only:
            return ("caption-filter", 1)
        target = str(Path(path).with_name("subtitled_1_" + Path(path).name))
        Path(target).write_bytes(b"captioned")
        return target

    def hook(path, clip, *, captions=None, mark=False):
        assert clip["viral_hook_text"] == "Hook"
        target = str(Path(path).with_name("hooked_1_" + Path(path).name))
        Path(target).write_bytes(b"hooked")
        calls.append("hook")
        return target, {"style": "classic"}

    def srt(_transcript, _start, _end, target):
        Path(target).write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n")
        return True

    deps = {"cut_clip": cut, "render_clip": render, "read_layouts": lambda _path: [],
            "split_ranges": lambda _layouts: [], "hook_wanted": lambda *_args: False,
            "reground": lambda *_args: None, "auto_hook_clip": hook,
            "auto_caption_clip": caption, "generate_srt": srt,
            "probe_duration": lambda _path: (30.0, 1 / 30)}
    result = render_candidate("window.ts", {"id": "live_1", "start": 2, "end": 32,
        "predicted_score": 80, "viral_hook_text": "Hook"},
        {"text": "Hola", "language": "es", "segments": []}, tmp_path,
        0, dependencies=deps)

    assert calls == ["render", "caption_plan", "hook", "caption"]
    assert Path(result["path"]).exists()
    assert Path(result["canonical_path"]).exists()
    assert Path(result["srt_path"]).exists()
    assert result["clip"]["source_window_id"] == "live_1"
    assert result["clip"]["file"].startswith("subtitled_")
    assert result["clip"]["rendered_duration_seconds"] == 30.0
    assert not list(tmp_path.glob("*.cut.mp4"))


def test_clipper_rejects_rendered_duration_outside_session_bounds(tmp_path):
    def render(_source, target, *_args, **_kwargs):
        Path(target).write_bytes(b"video")
        return True

    deps = {
        "cut_clip": lambda _source, target, *_args: Path(target).write_bytes(b"cut"),
        "render_clip": render,
        "read_layouts": lambda _path: [], "split_ranges": lambda _layouts: [],
        "hook_wanted": lambda *_args: False, "reground": lambda *_args: None,
        "auto_hook_clip": lambda *_args, **_kwargs: None,
        "auto_caption_clip": lambda *_args, **_kwargs: None,
        "generate_srt": lambda *_args: None,
        "probe_duration": lambda _path: (29.0, 0.01),
    }

    with pytest.raises(RuntimeError, match="fuera del rango"):
        render_candidate("window.ts", {"id": "live_short", "start": 0, "end": 30,
                         "min_clip_seconds": 30, "max_clip_seconds": 60},
                        {"text": "", "language": "", "segments": []}, tmp_path, 0,
                        dependencies=deps)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg/ffprobe are required for the real-duration check")
def test_clipper_measures_duration_of_the_final_video_with_ffprobe(tmp_path):
    def render(_source, target, *_args, **_kwargs):
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=64x64:r=25", "-t", "10", "-an", "-c:v", "libx264",
            "-preset", "ultrafast", target,
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True

    deps = {
        "cut_clip": lambda *_args: None, "render_clip": render,
        "read_layouts": lambda _path: [], "split_ranges": lambda _layouts: [],
        "hook_wanted": lambda *_args: False, "reground": lambda *_args: None,
        "auto_hook_clip": lambda *_args, **_kwargs: None,
        "auto_caption_clip": lambda *_args, **_kwargs: None,
        "generate_srt": lambda *_args: None,
    }
    result = render_candidate("window.ts", {"id": "live_probe", "start": 0, "end": 10,
                                              "min_clip_seconds": 10, "max_clip_seconds": 20},
                             {"text": "", "language": "", "segments": []}, tmp_path, 0,
                             dependencies=deps)

    assert result["clip"]["rendered_duration_seconds"] == pytest.approx(10, abs=0.05)
