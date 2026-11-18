"""Segment index and rolling retention with pinning for queued renders."""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    index: int
    path: Path
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


class SegmentBuffer:
    def __init__(self, directory: str | Path, *, retention_seconds: int = 1200):
        self.directory = Path(directory)
        self.retention_seconds = max(1, int(retention_seconds))
        self.pinned: set[int] = set()

    @staticmethod
    def read_csv(path: str | Path) -> list[Segment]:
        path = Path(path)
        if not path.exists():
            return []
        entries = []
        offset = 0.0
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv.reader(file):
                if not row:
                    continue
                try:
                    segment_path = Path(row[0].strip().strip('"'))
                    start_pts = float(row[1].strip().strip('"')) if len(row) > 1 else 0.0
                    end_pts = float(row[2].strip().strip('"')) if len(row) > 2 else start_pts
                except (ValueError, IndexError):
                    continue
                if not segment_path.is_absolute():
                    segment_path = path.parent / segment_path
                try:
                    index = int(segment_path.stem.rsplit("_", 1)[-1])
                except ValueError:
                    index = len(entries)
                duration = max(0.0, end_pts - start_pts)
                entries.append(Segment(index, segment_path, offset, max(0.0, duration)))
                offset += max(0.0, duration)
        return entries

    def refresh(self) -> list[Segment]:
        paths = sorted(self.directory.glob("segments_*.csv"))
        if not paths:
            paths = [self.directory / "segments.csv"]
        entries = []
        offset = 0.0
        for list_path in paths:
            for entry in self.read_csv(list_path):
                entries.append(Segment(entry.index, entry.path, offset, entry.duration))
                offset += entry.duration
        return sorted(entries, key=lambda entry: entry.index)

    def pin(self, indices) -> None:
        self.pinned.update(int(index) for index in indices)

    def unpin(self, indices) -> None:
        self.pinned.difference_update(int(index) for index in indices)

    def prune(self, *, now: float | None = None) -> list[Path]:
        now = time.time() if now is None else now
        entries = self.refresh()
        removed = []
        # CSV offsets are relative to the session. Use segment file mtime for
        # wall-clock retention so restarts and discontinuities remain safe.
        for entry in entries:
            if entry.index in self.pinned or not entry.path.exists():
                continue
            try:
                expired = now - entry.path.stat().st_mtime > self.retention_seconds
            except OSError:
                continue
            if expired:
                entry.path.unlink(missing_ok=True)
                removed.append(entry.path)
        return removed
