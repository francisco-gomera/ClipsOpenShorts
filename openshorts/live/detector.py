"""Fuse rolling audio peaks and transcript cues into live clip candidates."""
from __future__ import annotations

import itertools
import re
from bisect import bisect_left, bisect_right

from clip_selection import dedupe_overlapping, snap_clip_to_words

from .config import (CLIP_MAX_SECONDS, CLIP_MIN_SECONDS, COOLDOWN_SECONDS,
                     KEYWORD_SOLO_SCORE, KEYWORD_WINDOW_SECONDS,
                     MAX_CONFIGURABLE_CLIP_SECONDS, MIN_CONFIGURABLE_CLIP_SECONDS,
                     STRONG_AUDIO_Z)
from .signals import AudioPeakDetector, REACTION_WORDS, reaction_score


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", (text or "").lower())


def _keyword_hits(segments: list[dict], language: str) -> list[dict]:
    lang = (language or "").split("-")[0].lower()
    phrases = REACTION_WORDS.get(lang, set()) | REACTION_WORDS["es"] | REACTION_WORDS["en"]
    token_phrases = [(phrase, _tokens(phrase)) for phrase in phrases]
    by_first = {}
    for phrase, phrase_tokens in token_phrases:
        if phrase_tokens:
            by_first.setdefault(phrase_tokens[0], []).append((phrase, phrase_tokens))
    hits = []
    for segment in segments:
        words = segment.get("words") or []
        first_tokens = []
        for word in words:
            parts = _tokens(word.get("word", ""))
            first_tokens.append(parts[0] if parts else "")
        for index in range(len(words)):
            for phrase, phrase_tokens in by_first.get(first_tokens[index], ()):
                if not phrase_tokens or index + len(phrase_tokens) > len(words):
                    continue
                if first_tokens[index:index + len(phrase_tokens)] == phrase_tokens:
                    start = float(words[index]["start"])
                    end = float(words[index + len(phrase_tokens) - 1]["end"])
                    hits.append({"start": start, "end": end, "phrase": phrase,
                                 "score": reaction_score(phrase),
                                 "explicit": phrase in {"clipea esto", "clip it", "clip this"}})
    return hits


class LiveDetector:
    def __init__(self, *, cooldown_seconds: int = COOLDOWN_SECONDS,
                 min_seconds: int = CLIP_MIN_SECONDS, max_seconds: int = CLIP_MAX_SECONDS,
                 audio_detector: AudioPeakDetector | None = None):
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        if (isinstance(min_seconds, bool) or not isinstance(min_seconds, int)
                or isinstance(max_seconds, bool) or not isinstance(max_seconds, int)
                or not MIN_CONFIGURABLE_CLIP_SECONDS <= min_seconds <= MAX_CONFIGURABLE_CLIP_SECONDS
                or not MIN_CONFIGURABLE_CLIP_SECONDS <= max_seconds <= MAX_CONFIGURABLE_CLIP_SECONDS
                or min_seconds > max_seconds):
            raise ValueError("El rango de duración live debe estar entre 10 y 240 segundos.")
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self.audio_detector = audio_detector or AudioPeakDetector()
        self._ids = itertools.count(1)
        self._recent: list[dict] = []
        self._last_start: float | None = None
        self._pending: list[dict] = []
        self._keyword_scanned_until = 0.0
        self._keyword_hits_seen: set[tuple[str, float]] = set()
        self.last_metrics = {}

    def detect(self, buckets: list[dict], transcript: dict, *, latest_time: float | None = None) -> list[dict]:
        peaks = self.audio_detector.add(buckets)
        metric = {"audio_peaks": len(peaks), "keyword_hits": 0,
                  "rejected_weak_signal": 0, "rejected_cooldown": 0,
                  "rejected_bounds": 0, "rejected_overlap": 0,
                  "pending": 0, "candidates": 0}
        latest_time = float(latest_time if latest_time is not None else max(
            [p["end"] for p in peaks] + [0.0]))
        rolling = hasattr(transcript, "window") and hasattr(transcript, "segments")
        if rolling:
            # ASR timestamps can arrive behind capture time. Rescan a bounded
            # tail and deduplicate hits so late words still reach the detector.
            scan_start = max(0.0, self._keyword_scanned_until - 120.0)
            segments = transcript.segments(scan_start, latest_time)
            language = transcript.language
        else:
            segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
            language = transcript.get("language", "") if isinstance(transcript, dict) else ""
        keywords = _keyword_hits(segments, language)
        metric["keyword_hits"] = len(keywords)
        if rolling:
            keywords = [hit for hit in keywords
                        if (hit["phrase"], round(hit["start"], 1)) not in self._keyword_hits_seen]
            for hit in keywords:
                self._keyword_hits_seen.add((hit["phrase"], round(hit["start"], 1)))
            self._keyword_scanned_until = max(self._keyword_scanned_until, latest_time)
            self._keyword_hits_seen = {key for key in self._keyword_hits_seen
                                       if key[1] >= latest_time - 122.0}
            words = []
        else:
            words = [{"w": word.get("word", ""), "s": float(word["start"]), "e": float(word["end"])}
                     for segment in segments for word in segment.get("words", [])]
        events = [(peak["start"], "audio", peak) for peak in peaks]
        events += [(hit["start"], "keyword", hit) for hit in keywords]
        events.sort(key=lambda item: item[0])
        candidates = []
        consumed = set()
        possible = list(self._pending)
        self._pending = []
        event_points = [event[0] for event in events]
        for i, (at, kind, payload) in enumerate(events):
            if i in consumed:
                continue
            left = bisect_left(event_points, at - KEYWORD_WINDOW_SECONDS)
            right = bisect_right(event_points, at + KEYWORD_WINDOW_SECONDS)
            nearby = [(j, k, p) for j, (point, k, p) in enumerate(events[left:right], start=left)
                      if j != i and abs(point - at) <= KEYWORD_WINDOW_SECONDS]
            audio = payload if kind == "audio" else next((p for _, k, p in nearby if k == "audio"), None)
            keyword = payload if kind == "keyword" else next((p for _, k, p in nearby if k == "keyword"), None)
            if audio and keyword:
                consumed.update(j for j, k, _ in nearby if k in ("audio", "keyword"))
            audio_z = float(audio.get("z", 0)) if audio else 0.0
            keyword_score = float(keyword.get("score", 0)) if keyword else 0.0
            strong = (audio_z >= STRONG_AUDIO_Z
                      or bool(keyword and (keyword.get("explicit")
                                           or keyword_score >= KEYWORD_SOLO_SCORE)))
            if not strong and not (audio and keyword):
                metric["rejected_weak_signal"] += 1
                continue
            signal_weights = (0.45 if audio else 0.0) + (0.20 if keyword else 0.0)
            score = ((0.45 * min(1.0, audio_z / 6.0 if audio else 0.0)
                      + 0.20 * keyword_score) / signal_weights) if signal_weights else 0.0
            duration = round(self.min_seconds + score * (self.max_seconds - self.min_seconds))
            possible.append({"at": at, "duration": duration, "score": score,
                             "audio_z": audio_z, "keyword_score": keyword_score,
                             "keyword": keyword.get("phrase") if keyword else None,
                             "signals": [name for name, present in (("audio", audio), ("keyword", keyword)) if present],
                             "why": "Pico de audio" + (f" y reacción: {keyword['phrase']}" if keyword else "")})

        for item in possible:
            if latest_time < self.min_seconds:
                self._pending.append(item)
                continue
            duration = min(int(item["duration"]), int(latest_time))
            if duration < self.min_seconds:
                self._pending.append(item)
                continue
            after = min(15.0, duration * 0.35)
            preferred_start = float(item["at"]) - (duration - after)
            start = max(0.0, min(preferred_start, latest_time - duration))
            end = start + duration
            if self._last_start is not None and start - self._last_start < self.cooldown_seconds:
                metric["rejected_cooldown"] += 1
                continue
            if rolling:
                candidate_words = transcript.window(max(0.0, start - 5.0), end + 5.0)
                snap_words = [{"w": word.get("word", ""), "s": float(word["start"]),
                               "e": float(word["end"])} for word in candidate_words]
            else:
                snap_words = words
            if snap_words:
                start, end = snap_clip_to_words(start, end, snap_words, latest_time,
                                                min_duration=self.min_seconds,
                                                max_duration=self.max_seconds)
            if (end - start < self.min_seconds - 0.01
                    or end - start > self.max_seconds + 0.01
                    or start < 0 or end > latest_time + 0.01):
                metric["rejected_bounds"] += 1
                continue
            candidate = {"id": f"live_{next(self._ids):06d}", "start": round(start, 3),
                         "end": round(end, 3), "predicted_score": round(item["score"] * 100),
                         "audio_z": item["audio_z"], "keyword_score": item["keyword_score"],
                         "keyword": item["keyword"], "signals": item["signals"], "why": item["why"],
                         "min_clip_seconds": self.min_seconds,
                         "max_clip_seconds": self.max_seconds}
            accepted = dedupe_overlapping(self._recent + [candidate])
            if candidate not in accepted:
                metric["rejected_overlap"] += 1
                continue
            self._recent = accepted[-12:]
            self._last_start = start
            candidates.append(candidate)
        metric["candidates"] = len(candidates)
        metric["pending"] = len(self._pending)
        self.last_metrics = metric
        return candidates

    def discard_pending(self) -> int:
        """Drop highlights that ended before enough source existed for a valid clip."""
        discarded = len(self._pending)
        self._pending.clear()
        return discarded
