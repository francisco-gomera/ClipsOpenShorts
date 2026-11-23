"""Deterministic segment builders for non-AI generation modes."""

from __future__ import annotations

import json
import math
from typing import Any

GENERATION_MODES = {"smart", "sequential", "full", "manual"}
MAX_CLIP_SECONDS = 240.0
MIN_CLIP_SECONDS = 5.0
MAX_CLIPS = 15


def parse_manual_segments(raw: Any) -> list[dict[str, float]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("manual_segments must be valid JSON") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("manual mode requires at least one segment")
    if len(raw) > MAX_CLIPS:
        raise ValueError(f"manual mode supports at most {MAX_CLIPS} clips")
    segments = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or "start" not in item or "end" not in item:
            raise ValueError(f"manual segment {i} requires start and end")
        try:
            start, end = float(item["start"]), float(item["end"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"manual segment {i} times must be numbers") from exc
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError(f"manual segment {i} times must be finite")
        if start < 0 or end <= start:
            raise ValueError(f"manual segment {i} must have 0 <= start < end")
        if end - start < MIN_CLIP_SECONDS or end - start > MAX_CLIP_SECONDS:
            raise ValueError(f"manual clips must be between {MIN_CLIP_SECONDS:g} and {MAX_CLIP_SECONDS:g} seconds")
        segments.append({"start": start, "end": end})
    ordered = sorted(segments, key=lambda s: s["start"])
    if any(b["start"] < a["end"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("manual segments must not overlap")
    return segments


def build_sequential_clips(video_duration: float, count: int, clip_seconds: float) -> list[dict[str, float]]:
    duration, seconds = float(video_duration), float(clip_seconds)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be positive")
    if isinstance(count, bool) or int(count) != count or not 1 <= int(count) <= MAX_CLIPS:
        raise ValueError(f"clip count must be between 1 and {MAX_CLIPS}")
    if not math.isfinite(seconds) or not MIN_CLIP_SECONDS <= seconds <= MAX_CLIP_SECONDS:
        raise ValueError(f"clip duration must be between {MIN_CLIP_SECONDS:g} and {MAX_CLIP_SECONDS:g} seconds")
    if duration + 1e-6 < int(count) * seconds:
        raise ValueError("video is too short for the requested number of consecutive clips")
    return [{"start": i * seconds, "end": (i + 1) * seconds} for i in range(int(count))]


def build_full_clip(video_duration: float) -> list[dict[str, float]]:
    duration = float(video_duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be positive")
    return [{"start": 0.0, "end": duration}]


def validate_segments(segments: list[dict[str, float]], video_duration: float) -> list[dict[str, float]]:
    duration = float(video_duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be positive")
    if any(s["end"] > duration + 0.05 for s in segments):
        raise ValueError("a selected segment ends after the source video")
    return segments
