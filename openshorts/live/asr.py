"""Incremental CPU Whisper adapter for live session windows."""
from __future__ import annotations

import os
import re
import time
from threading import Lock

from .config import WHISPER_MODEL

_MODEL_LOCK = Lock()


class IncrementalTranscriber:
    """Transcribe overlapping windows and emit the repository transcript shape.

    A live session runs in its own child process, so setting the established
    Whisper env knobs here cannot change ordinary API/job transcription.
    """
    def __init__(self, *, model: str = WHISPER_MODEL, block_seconds: int = 30,
                 overlap_seconds: int = 2, transcribe=None, slot_factory=None):
        self.model = model
        self.block_seconds = max(5, int(block_seconds))
        self.overlap_seconds = max(0, int(overlap_seconds))
        self._transcribe = transcribe
        self._slot_factory = slot_factory
        self._previous_words: list[dict] = []
        self.language = ""
        self.rtf = 0.0
        self._slow_streak = 0
        self._asr_enabled = True
        self.notices: list[str] = []
        self._model_used = False

    def _run_model(self, wav_path):
        if self._transcribe:
            return self._transcribe(wav_path)
        os.environ["WHISPER_MODEL"] = self.model
        os.environ["WHISPER_DEVICE"] = "cpu"
        os.environ["WHISPER_COMPUTE"] = "int8"
        os.environ["WHISPER_CPU_THREADS"] = os.environ.get("WHISPER_CPU_THREADS", "")
        import transcribe_backends
        from subtitles import WHISPER_TRANSCRIBE_PARAMS, merge_continuation_words
        slot_factory = self._slot_factory or transcribe_backends.host_asr_slot
        with _MODEL_LOCK, slot_factory():
            segments, info = transcribe_backends.run_whisper_transcription(
                wav_path, **WHISPER_TRANSCRIBE_PARAMS)
        self._model_used = True
        out = []
        text_parts = []
        for segment in segments:
            words = [{"word": word.word, "start": float(word.start), "end": float(word.end)}
                     for word in (segment.words or [])]
            out.append({"start": float(segment.start), "end": float(segment.end),
                        "text": segment.text, "words": merge_continuation_words(words)})
            text_parts.append(segment.text.strip())
        return {"text": " ".join(part for part in text_parts if part),
                "language": getattr(info, "language", "") or "", "segments": out}

    @staticmethod
    def _dedupe_words(words: list[dict], *, overlap_start: float | None = None) -> list[dict]:
        result = []
        for word in sorted(words, key=lambda item: (item["start"], item["end"])):
            key = re.sub(r"\W+", "", word["word"].lower())
            if not key:
                continue
            duplicate = any(re.sub(r"\W+", "", old["word"].lower()) == key
                            and (round(float(old["start"]), 1) == round(float(word["start"]), 1)
                                 or (overlap_start is not None
                                     and float(old["start"]) >= overlap_start
                                     and abs(float(old["start"]) - float(word["start"])) <= 0.45))
                            for old in result)
            if duplicate:
                continue
            result.append(word)
        return result

    def transcribe_block(self, wav_path, *, session_start: float, audio_duration: float | None = None) -> dict:
        duration = float(audio_duration or self.block_seconds)
        if not self._asr_enabled:
            return {"text": "", "language": self.language, "segments": [], "rtf": self.rtf,
                    "audio_duration": duration, "elapsed_seconds": 0.0,
                    "notice": "ASR detenido por carga; se mantienen las señales de audio"}
        started = time.monotonic()
        transcript = self._run_model(wav_path)
        elapsed = time.monotonic() - started
        self.rtf = elapsed / max(duration, 0.001)
        if self.rtf > 0.8:
            self._slow_streak += 1
        else:
            self._slow_streak = 0
        notice = None
        if self._slow_streak >= 3:
            self._slow_streak = 0
            if self.model == "small":
                self.model = "base"
                notice = "transcripción degradada a base por carga"
            else:
                self._asr_enabled = False
                notice = "ASR detenido por carga; se mantienen las señales de audio"
            self.notices.append(notice)
        self.language = transcript.get("language") or self.language
        offset = float(session_start)
        current_words = []
        for segment in transcript.get("segments", []):
            for word in segment.get("words", []):
                current_words.append({**word, "start": float(word["start"]) + offset,
                                      "end": float(word["end"]) + offset})
        overlap_start = offset - self.overlap_seconds - 1.0
        previous = [word for word in self._previous_words if float(word["end"]) >= overlap_start]
        combined = self._dedupe_words(previous + current_words, overlap_start=overlap_start)
        self._previous_words = [word for word in combined if float(word["end"]) >= overlap_start]
        # Reconstruct segment text and word timestamps in absolute session time.
        segments = []
        for segment in transcript.get("segments", []):
            start, end = float(segment["start"]) + offset, float(segment["end"]) + offset
            words = [word for word in combined
                     if word["end"] >= start - 0.05 and word["start"] <= end + 0.05]
            segments.append({"start": start, "end": end, "text": segment.get("text", ""), "words": words})
        return {"text": transcript.get("text", ""), "language": self.language,
                "segments": segments, "rtf": self.rtf, "audio_duration": duration,
                "elapsed_seconds": elapsed, "notice": notice}

    def close(self) -> None:
        """Release resident models when the live session ends."""
        if not self._model_used:
            return
        import transcribe_backends
        transcribe_backends.release_models()
        self._model_used = False


def block_starts(duration: float, *, block_seconds: int = 30, overlap_seconds: int = 2):
    """Yield session-time block starts, advancing by block length minus overlap."""
    step = max(1, block_seconds - overlap_seconds)
    start = 0
    while start < duration:
        yield start
        start += step
