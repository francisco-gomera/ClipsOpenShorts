"""Audio extraction and rolling loudness measurements for live segments."""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path


def extract_wav(source: str | Path, output: str | Path, *, start: float = 0,
                duration: float | None = None, ffmpeg: str = "ffmpeg") -> Path:
    """Convert a media range to mono 16 kHz PCM suitable for Whisper."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(source)]
    if duration is not None:
        cmd += ["-t", f"{max(0.01, duration):.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return output


def extract_wav_window(segments: list[str | Path], output: str | Path, *,
                       start: float = 0, duration: float = 30,
                       ffmpeg: str = "ffmpeg") -> Path:
    """Join local transport-stream segments and extract one session-time range."""
    if not segments:
        raise ValueError("No hay segmentos de audio disponibles")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, listing = tempfile.mkstemp(prefix="live-concat-", suffix=".txt", dir=str(output.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            for segment in segments:
                escaped = str(Path(segment).resolve()).replace("'", "'\\''")
                file.write(f"file '{escaped}'\n")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
               "-safe", "0", "-i", listing]
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-t", f"{max(0.01, duration):.3f}", "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(output)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        try:
            os.unlink(listing)
        except OSError:
            pass
    return output


def rms_db_buckets(wav_path: str | Path, *, bucket_seconds: int = 1) -> list[dict[str, float]]:
    """Measure PCM RMS in one-second buckets (reported as dBFS)."""
    bucket_seconds = max(1, int(bucket_seconds))
    with wave.open(str(wav_path), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        if width != 2:
            raise ValueError("Se esperaba WAV PCM de 16 bits")
        frames_per = rate * bucket_seconds
        buckets = []
        start = 0.0
        while True:
            data = wav.readframes(frames_per)
            if not data:
                break
            sample_count = len(data) // 2
            samples = memoryview(data).cast("h")
            mean_square = sum(sample * sample for sample in samples) / max(1, sample_count)
            rms = math.sqrt(mean_square) / 32768.0
            db = 20.0 * math.log10(max(rms, 1e-8))
            buckets.append({"start": start, "end": start + len(data) / (2 * rate * channels), "db": db})
            start += bucket_seconds
        return buckets


def aggregate_buckets(buckets: list[dict[str, float]], seconds: int = 5) -> list[dict[str, float]]:
    """Aggregate adjacent per-second dBFS buckets into fixed windows."""
    seconds = max(1, int(seconds))
    result = []
    for offset in range(0, len(buckets), seconds):
        group = buckets[offset:offset + seconds]
        if group:
            result.append({"start": group[0]["start"], "end": group[-1]["end"],
                           "db": sum(item["db"] for item in group) / len(group)})
    return result
