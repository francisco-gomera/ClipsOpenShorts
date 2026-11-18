"""Build an isolated source window from rolling MPEG-TS segments."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def select_window_segments(segments, start: float, end: float):
    selected = [item for item in segments if item.end > start and item.start < end]
    if not selected:
        raise ValueError("No hay segmentos retenidos para esta ventana")
    selected.sort(key=lambda item: item.start)
    for left, right in zip(selected, selected[1:]):
        if right.start - left.end > 1.0:
            raise ValueError("La ventana del directo contiene un hueco de captura")
    return selected


def translate_words_to_window(words: list[dict], *, offset: float, start: float, end: float):
    """Keep intersecting session-time words and shift them to the window origin."""
    translated = []
    for word in words:
        word_start, word_end = float(word["start"]), float(word["end"])
        if word_end < start or word_start > end:
            continue
        translated.append({**word, "start": max(0.0, word_start - offset),
                           "end": max(0.0, word_end - offset)})
    return translated


def build_source_window(buffer, candidate: dict, directory: str | Path, *,
                        margin: float = 10.0, ffmpeg: str = "ffmpeg", runner=subprocess.run):
    """Concatenate the candidate's segment range into a seekable TS source file."""
    desired_start = max(0.0, float(candidate["start"]) - margin)
    desired_end = float(candidate["end"]) + margin
    selected = select_window_segments(buffer.refresh(), desired_start, desired_end)
    offset = selected[0].start
    actual_end = selected[-1].end
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{candidate.get('id', 'clip')}_window.ts"
    fd, listing = tempfile.mkstemp(prefix="live-window-", suffix=".txt", dir=str(output_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            for segment in selected:
                escaped = str(Path(segment.path).resolve()).replace("'", "'\\''")
                file.write(f"file '{escaped}'\n")
        start_in_concat = max(0.0, desired_start - offset)
        duration = max(0.1, min(actual_end, desired_end) - desired_start)
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
                   "-safe", "0", "-i", listing, "-ss", f"{start_in_concat:.3f}",
                   "-t", f"{duration:.3f}", "-c", "copy", "-avoid_negative_ts", "make_zero",
                   "-fflags", "+genpts", "-f", "mpegts", str(output)]
        runner(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        try:
            os.unlink(listing)
        except OSError:
            pass
    local_start = float(candidate["start"]) - desired_start
    local_end = float(candidate["end"]) - desired_start
    return {"path": str(output), "offset": desired_start,
            "start": max(0.0, local_start), "end": max(0.0, local_end),
            "segment_indices": [item.index for item in selected],
            "actual_duration": duration}
