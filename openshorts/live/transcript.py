"""Bounded, time-indexed transcript storage for live sessions."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import re


def _normalise(word: dict) -> str:
    return re.sub(r"\W+", "", str(word.get("word", "")).lower())


class RollingTranscript:
    def __init__(self, *, max_segment_chars: int = 1200):
        self.words: list[dict] = []
        self._starts: list[float] = []
        self.language = ""
        self.max_segment_chars = max(100, int(max_segment_chars))
        self._pinned: dict[str, tuple[float, float]] = {}

    def add_words(self, words: list[dict]) -> None:
        incoming = sorted((dict(word) for word in words
                           if word.get("word") and word.get("start") is not None
                           and word.get("end") is not None),
                          key=lambda item: (float(item["start"]), float(item["end"])))
        if not incoming:
            return
        first_start = float(incoming[0]["start"])
        recent_from = first_start - 1.0
        recent_index = bisect_left(self._starts, recent_from)
        recent = self.words[recent_index:]
        recent_keys = {(_normalise(word), round(float(word["start"]), 1)) for word in recent}
        additions = []
        for word in incoming:
            word["start"], word["end"] = float(word["start"]), float(word["end"])
            norm = _normalise(word)
            key = (norm, round(word["start"], 1))
            if not norm or key in recent_keys:
                continue
            # Whisper can shift timestamps slightly in the overlapping block.
            duplicate = any(_normalise(old) == norm
                            and abs(float(old["start"]) - word["start"]) <= 0.45
                            for old in recent if old not in additions)
            if not duplicate:
                additions.append(word)
                recent_keys.add(key)
        if additions:
            self.words.extend(additions)
            self.words.sort(key=lambda item: (float(item["start"]), float(item["end"])))
            self._starts = [float(word["start"]) for word in self.words]

    def window(self, start: float, end: float) -> list[dict]:
        if not self.words or end < start:
            return []
        left = max(0, bisect_left(self._starts, float(start)) - 1)
        right = bisect_right(self._starts, float(end))
        return [dict(word) for word in self.words[left:right]
                if float(word["end"]) >= start and float(word["start"]) <= end]

    def segments(self, start: float, end: float, *, gap: float = 1.2) -> list[dict]:
        words = self.window(start, end)
        groups: list[list[dict]] = []
        for word in words:
            if (not groups or float(word["start"]) - float(groups[-1][-1]["end"]) > gap
                    or sum(len(str(item.get("word", ""))) for item in groups[-1]) >= self.max_segment_chars):
                groups.append([word])
            else:
                groups[-1].append(word)
        return [{"start": group[0]["start"], "end": group[-1]["end"],
                 "text": "".join(str(word.get("word", "")) for word in group).strip(),
                 "words": group} for group in groups]

    def snapshot(self, start: float, end: float) -> dict:
        segments = self.segments(start, end)
        return {"text": " ".join(item["text"] for item in segments),
                "language": self.language, "segments": segments}

    def pin(self, key: str, start: float, end: float) -> None:
        self._pinned[str(key)] = (float(start), float(end))

    def unpin(self, key: str) -> None:
        self._pinned.pop(str(key), None)

    def prune(self, keep_from: float) -> int:
        if self._pinned:
            keep_from = min(float(keep_from), min(span[0] for span in self._pinned.values()))
        index = bisect_left(self._starts, float(keep_from))
        removed = index
        self.words = self.words[index:]
        self._starts = self._starts[index:]
        return removed
