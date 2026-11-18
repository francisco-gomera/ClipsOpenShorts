"""Render live candidates through the existing OpenShorts clip pipeline."""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
from pathlib import Path

from .config import REFRAME


@contextlib.contextmanager
def _live_render_env():
    desired = {"AUTO_HOOK": "1", "AUTO_CAPTIONS": "1", "CLIP_WORKERS": "1", "WATERMARK": "0"}
    old = {key: os.environ.get(key) for key in desired}
    os.environ.update(desired)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _pipeline():
    import main
    import ffmpeg_utils
    import hook_grounding
    import layout_ranges
    import subtitles
    return {"render_clip": main.render_clip, "auto_hook_clip": main.auto_hook_clip,
            "auto_caption_clip": main.auto_caption_clip, "cut_clip": ffmpeg_utils.cut_clip,
            "read_layouts": layout_ranges.read, "split_ranges": layout_ranges.split_ranges,
            "hook_wanted": hook_grounding.wanted, "reground": hook_grounding.reground,
            "generate_srt": subtitles.generate_srt}


def _vertical_source(path: str) -> bool:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
                                check=True, capture_output=True, text=True, timeout=10)
        width, height = (int(value) for value in result.stdout.strip().split("x", 1))
        return height >= width
    except Exception:
        return False


def _force_strategy(path: str, mode: str) -> str | None:
    if mode == "fast":
        return "TRACK" if _vertical_source(path) else "GENERAL"
    return None


def render_candidate(window_path: str, candidate: dict, transcript: dict,
                     output_dir: str | Path, index: int, *, dependencies=None,
                     reframe: str | None = None) -> dict:
    """Cut, reframe, ground hook, add hook/captions, and create an SRT sidecar."""
    deps = dependencies or _pipeline()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(candidate.get("id") or index + 1))
    basename = f"live_clip_{index + 1}.mp4"
    temporary = output_dir / f".{basename}.cut.mp4"
    final = output_dir / basename
    start, end = float(candidate["start"]), float(candidate["end"])
    clip = dict(candidate)
    clip["source_window_id"] = str(candidate.get("id", f"live_{index + 1}"))

    with _live_render_env():
        try:
            deps["cut_clip"](window_path, str(temporary), start, end, index + 1)
            success = deps["render_clip"](
                str(temporary), str(final), "vertical",
                force_strategy=_force_strategy(window_path, reframe or REFRAME),
                subtitle_band=None)
            if not success or not final.exists():
                raise RuntimeError("El render no produjo un archivo reproducible")
            layouts = deps["read_layouts"](str(final))
            clip["layout_ranges"] = layouts
            if deps["hook_wanted"](layouts, end - start):
                deps["reground"](str(final), clip, transcript, start, end)

            deliver = str(final)
            captioned = None
            split_ranges = deps["split_ranges"](layouts)
            plan = None
            if (clip.get("viral_hook_text") or "").strip():
                plan = deps["auto_caption_clip"](str(final), transcript, start, end,
                                                  split_ranges=split_ranges, plan_only=True)
            hooked = deps["auto_hook_clip"](str(final), clip, captions=plan, mark=False)
            if hooked:
                deliver, hook_config = hooked
                clip["auto_hook"] = dict(hook_config)
                captioned = clip["auto_hook"].pop("_captioned", None)
            if not captioned:
                captioned = deps["auto_caption_clip"](deliver, transcript, start, end,
                                                      split_ranges=split_ranges, mark=False)
            if captioned:
                deliver = captioned
            srt_path = output_dir / f"live_clip_{index + 1}_{clip_id}.srt"
            deps["generate_srt"](transcript, start, end, str(srt_path))
            clip.update({"file": os.path.basename(deliver), "canonical_file": basename,
                         "srt_file": srt_path.name if srt_path.exists() else None,
                         "start": start, "end": end})
            return {"clip": clip, "path": deliver, "canonical_path": str(final),
                    "srt_path": str(srt_path) if srt_path.exists() else None,
                    "layout_ranges": layouts}
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
