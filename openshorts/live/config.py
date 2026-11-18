"""Live clipping settings shared by the capture and analysis workers."""
from __future__ import annotations

import os


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


SEGMENT_SECONDS = _int("LIVE_SEGMENT_SECONDS", 10)
BUFFER_MINUTES = _int("LIVE_BUFFER_MINUTES", 20)
WHISPER_MODEL = os.environ.get("LIVE_WHISPER_MODEL", "small")
MAX_QUEUE = _int("LIVE_MAX_QUEUE", 3)
COOLDOWN_SECONDS = _int("LIVE_COOLDOWN_SECONDS", 150)
CLIP_MIN_SECONDS = _int("LIVE_CLIP_MIN", 25)
CLIP_MAX_SECONDS = max(CLIP_MIN_SECONDS, _int("LIVE_CLIP_MAX", 60))
AUDIO_WARMUP_SECONDS = _int("LIVE_AUDIO_WARMUP_SECONDS", 120, 0)
AUDIO_PEAK_Z = _float("LIVE_AUDIO_PEAK_Z", 2.5)
STRONG_AUDIO_Z = _float("LIVE_STRONG_AUDIO_Z", 4.0)
KEYWORD_WINDOW_SECONDS = _int("LIVE_KEYWORD_WINDOW_SECONDS", 20, 1)
KEYWORD_SOLO_SCORE = _float("LIVE_KEYWORD_SOLO_SCORE", 0.85)
JUDGE_MODE = os.environ.get("LIVE_JUDGE_MODE", "score")
LLM_TIMEOUT = _int("LIVE_LLM_TIMEOUT", 90)
REFRAME = os.environ.get("LIVE_REFRAME", "auto")
