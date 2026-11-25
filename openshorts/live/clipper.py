"""Render live candidates through the existing OpenShorts clip pipeline."""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
from pathlib import Path

from .config import (DEFAULT_CLIP_MAX_SECONDS, DEFAULT_CLIP_MIN_SECONDS, REFRAME,
                     validate_clip_duration_range)


def _probe_output_duration(path: str) -> tuple[float, float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate:format=duration", "-of", "json", path],
        check=True, capture_output=True, text=True, timeout=15)
    info = json.loads(result.stdout)
    duration = float(info["format"]["duration"])
    frame_rate = (info.get("streams") or [{}])[0].get("avg_frame_rate", "0/0")
    try:
        numerator, denominator = frame_rate.split("/", 1)
        fps = float(numerator) / float(denominator)
        tolerance = 1.0 / fps if fps > 0 else 0.05
    except (ValueError, ZeroDivisionError, AttributeError):
        tolerance = 0.05
    return duration, tolerance


@contextlib.contextmanager
def _live_render_env():
    desired = {"AUTO_HOOK": "0", "AUTO_CAPTIONS": "1", "CLIP_WORKERS": "1", "WATERMARK": "0"}
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
    import layout_ranges
    import subtitles
    return {"render_clip": main.render_clip, "auto_caption_clip": main.auto_caption_clip,
            "cut_clip": ffmpeg_utils.cut_clip,
            "read_layouts": layout_ranges.read, "split_ranges": layout_ranges.split_ranges,
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
                     reframe: str | None = None, on_phase=None) -> dict:
    """Cut and reframe the candidate, burn subtitles, and create an SRT sidecar."""
    def phase(name):
        if on_phase:
            on_phase(name)

    deps = dependencies or _pipeline()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(candidate.get("id") or index + 1))
    basename = f"live_clip_{index + 1}.mp4"
    temporary = output_dir / f".{basename}.cut.mp4"
    final = output_dir / basename
    start, end = float(candidate["start"]), float(candidate["end"])
    minimum, maximum = validate_clip_duration_range(
        candidate.get("min_clip_seconds", DEFAULT_CLIP_MIN_SECONDS),
        candidate.get("max_clip_seconds", DEFAULT_CLIP_MAX_SECONDS))
    requested_duration = end - start
    if requested_duration < minimum - 0.01 or requested_duration > maximum + 0.01:
        raise ValueError("El candidato no respeta la duración configurada para la sesión")
    clip = dict(candidate)
    clip["source_window_id"] = str(candidate.get("id", f"live_{index + 1}"))

    with _live_render_env():
        try:
            phase("cortando_fragmento")
            deps["cut_clip"](window_path, str(temporary), start, end, index + 1)
            phase("adaptando_vertical")
            success = deps["render_clip"](
                str(temporary), str(final), "vertical",
                force_strategy=_force_strategy(window_path, reframe or REFRAME),
                subtitle_band=None)
            if not success or not final.exists():
                raise RuntimeError("El render no produjo un archivo reproducible")
            phase("analizando_encuadre")
            layouts = deps["read_layouts"](str(final))
            clip["layout_ranges"] = layouts
            split_ranges = deps["split_ranges"](layouts)
            has_transcript = bool(transcript and transcript.get("segments"))
            if has_transcript:
                phase("generando_subtitulos")
            captioned = deps["auto_caption_clip"](str(final), transcript, start, end,
                                                  split_ranges=split_ranges, mark=False)
            deliver = str(final)
            if captioned:
                deliver = captioned
            phase("verificando_archivo")
            duration, tolerance = deps.get("probe_duration", _probe_output_duration)(deliver)
            if duration < minimum - tolerance or duration > maximum + tolerance:
                raise RuntimeError(
                    f"El clip renderizado dura {duration:.3f}s y queda fuera del rango "
                    f"{minimum}–{maximum}s (tolerancia {tolerance:.3f}s)")
            srt_path = output_dir / f"live_clip_{index + 1}_{clip_id}.srt"
            phase("generando_srt")
            deps["generate_srt"](transcript, start, end, str(srt_path))
            clip.update({"file": os.path.basename(deliver), "canonical_file": basename,
                         "srt_file": srt_path.name if srt_path.exists() else None,
                         "start": start, "end": end,
                         "rendered_duration_seconds": round(float(duration), 3)})
            phase("finalizado")
            return {"clip": clip, "path": deliver, "canonical_path": str(final),
                    "srt_path": str(srt_path) if srt_path.exists() else None,
                    "layout_ranges": layouts}
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
