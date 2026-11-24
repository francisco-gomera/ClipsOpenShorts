"""Measure steady-state live detector work after long simulated sessions."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from live.detector import LiveDetector
from live.transcript import RollingTranscript


def measure(hours: int, repeats: int = 30) -> float:
    duration = hours * 3600
    transcript = RollingTranscript()
    transcript.add_words([{"word": " palabra", "start": float(second),
                           "end": float(second) + 0.4}
                          for second in range(0, duration, 2)])
    detector = LiveDetector()
    detector._keyword_scanned_until = duration - 5
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        detector.detect([], transcript, latest_time=duration)
        samples.append(time.perf_counter() - started)
        detector._keyword_scanned_until = duration - 5
    return statistics.median(samples)


if __name__ == "__main__":
    for hours in (1, 4, 12, 24):
        print(f"{hours:>2} h: {measure(hours) * 1000:.3f} ms/call")
