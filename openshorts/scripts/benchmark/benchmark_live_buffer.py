"""Measure cached SegmentBuffer refresh for a day of 10-second segments."""
from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from live.buffer import SegmentBuffer


def measure(hours: int = 24, repeats: int = 100) -> float:
    with tempfile.TemporaryDirectory(prefix="live-buffer-benchmark-") as temporary:
        directory = Path(temporary)
        count = hours * 360
        with (directory / "segments_000000.csv").open("w", encoding="utf-8") as file:
            for index in range(count):
                start = index * 10
                file.write(f"seg_{index:06d}.ts,{start},{start + 10}\n")
        buffer = SegmentBuffer(directory)
        buffer.refresh()  # Include the full CSV parse as a separate cold pass.
        samples = []
        for _ in range(repeats):
            started = time.perf_counter()
            buffer.refresh()
            samples.append(time.perf_counter() - started)
        return statistics.median(samples)


if __name__ == "__main__":
    print(f"24 h cached refresh: {measure() * 1000:.3f} ms/call")
