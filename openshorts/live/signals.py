"""Robust audio/transcript signals used by the live candidate detector."""
from __future__ import annotations

import re
import statistics
from collections import deque
from typing import Iterable

from .config import AUDIO_PEAK_Z, AUDIO_WARMUP_SECONDS


REACTION_WORDS = {
    "es": {"increíble", "increible", "wow", "no puede ser", "madre mía", "madre mia",
           "vamos", "gol", "clipea esto", "clipéa esto"},
    "en": {"wow", "incredible", "no way", "let's go", "lets go", "clip it", "clip this"},
}

_EXPLICIT_CLIP_PHRASES = {"clipea esto", "clip it", "clip this"}
_STRONG_REACTION_PHRASES = {
    "increíble", "increible", "incredible", "no puede ser", "no way",
    "madre mía", "madre mia", "gol",
}


def reaction_score(phrase: str) -> float:
    if phrase in _EXPLICIT_CLIP_PHRASES:
        return 1.0
    if phrase in _STRONG_REACTION_PHRASES:
        return 0.9
    return 0.65


def robust_z_score(value: float, history: Iterable[float], *, floor: float = 1.0) -> float:
    values = list(history)
    if len(values) < 3:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median(abs(item - median) for item in values)
    scale = max(1.4826 * mad, floor)
    return (float(value) - median) / scale


class AudioPeakDetector:
    def __init__(self, *, history_seconds: int = 900, warmup_seconds: int = AUDIO_WARMUP_SECONDS,
                 threshold: float = AUDIO_PEAK_Z):
        self.history = deque()
        self.history_seconds = max(30, history_seconds)
        self.warmup_seconds = max(0, warmup_seconds)
        self.threshold = threshold

    def add(self, buckets: list[dict], *, session_offset: float = 0) -> list[dict]:
        peaks = []
        for bucket in buckets:
            start = float(bucket["start"]) + session_offset
            value = float(bucket["db"])
            baseline = [item[1] for item in self.history]
            z = robust_z_score(value, baseline)
            warm = start < self.warmup_seconds
            if not warm and z >= self.threshold:
                peaks.append({"start": start, "end": float(bucket["end"]) + session_offset,
                              "value": value, "z": z, "kind": "audio_peak"})
            self.history.append((start, value))
            cutoff = start - self.history_seconds
            while self.history and self.history[0][0] < cutoff:
                self.history.popleft()
        return peaks


def keyword_events(text: str, *, language: str = "") -> list[dict]:
    language = (language or "").lower().split("-")[0]
    words = set(REACTION_WORDS.get(language, set()) | REACTION_WORDS["en"] | REACTION_WORDS["es"])
    normalized = re.sub(r"\s+", " ", (text or "").lower())
    found = []
    for phrase in sorted(words, key=len, reverse=True):
        for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized):
            found.append({"text": phrase, "start_char": match.start(), "end_char": match.end(),
                          "kind": "reaction_keyword", "score": reaction_score(phrase)})
    return sorted(found, key=lambda item: item["start_char"])
