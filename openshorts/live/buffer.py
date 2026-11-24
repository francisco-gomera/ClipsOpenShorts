"""Segment index and rolling retention with pinning for queued renders."""
from __future__ import annotations

import csv
import threading
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
        self._lock = threading.RLock()
        self._readers: dict[Path, dict] = {}
        self._entries: dict[int, Segment] = {}
        self._deleted: set[int] = set()
        self.first_start: float | None = None
        self.latest_end: float = 0.0

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
        with self._lock:
            paths = sorted(self.directory.glob("segments_*.csv"))
            if not paths:
                paths = [self.directory / "segments.csv"]
            for list_path in paths:
                try:
                    size = list_path.stat().st_size
                except OSError:
                    continue
                reader = self._readers.get(list_path)
                if reader is None:
                    reader = {"pos": 0, "pending": b"", "base": self.latest_end,
                              "duration": 0.0, "entries": []}
                    self._readers[list_path] = reader
                if size < reader["pos"]:
                    for old in reader["entries"]:
                        self._deleted.add(old.index)
                    reader.update({"pos": 0, "pending": b"", "base": self.latest_end,
                                   "duration": 0.0, "entries": []})
                if size > reader["pos"]:
                    with list_path.open("rb") as file:
                        file.seek(reader["pos"])
                        data = reader["pending"] + file.read()
                    complete_end = data.rfind(b"\n") + 1
                    complete, reader["pending"] = data[:complete_end], data[complete_end:]
                    reader["pos"] = size
                    for raw_line in complete.splitlines():
                        try:
                            row = next(csv.reader([raw_line.decode("utf-8")]))
                            if not row:
                                continue
                            segment_path = Path(row[0].strip().strip('"'))
                            start_pts = float(row[1].strip().strip('"')) if len(row) > 1 else 0.0
                            end_pts = float(row[2].strip().strip('"')) if len(row) > 2 else start_pts
                            if not segment_path.is_absolute():
                                segment_path = list_path.parent / segment_path
                            index = int(segment_path.stem.rsplit("_", 1)[-1])
                        except (UnicodeDecodeError, csv.Error, ValueError, IndexError):
                            continue
                        duration = max(0.0, end_pts - start_pts)
                        entry = Segment(index, segment_path, reader["base"] + reader["duration"], duration)
                        reader["entries"].append(entry)
                        reader["duration"] += duration
                        self._entries[index] = entry
                        if not segment_path.exists():
                            self._deleted.add(index)
                        else:
                            self._deleted.discard(index)
                    self.latest_end = max(self.latest_end, reader["base"] + reader["duration"])
            entries = sorted((entry for index, entry in self._entries.items()
                              if index not in self._deleted), key=lambda entry: entry.index)
            self.first_start = entries[0].start if entries else None
            self.latest_end = max((entry.end for entry in self._entries.values()), default=self.latest_end)
            return entries

    def retained(self) -> list[Segment]:
        """Return the current in-memory snapshot without reading CSV files."""
        with self._lock:
            return sorted((entry for index, entry in self._entries.items()
                           if index not in self._deleted), key=lambda entry: entry.index)

    def pin(self, indices) -> None:
        with self._lock:
            self.pinned.update(int(index) for index in indices)

    def unpin(self, indices) -> None:
        with self._lock:
            self.pinned.difference_update(int(index) for index in indices)

    def prune(self, entries: list[Segment] | None = None, *, now: float | None = None) -> list[Path]:
        now = time.time() if now is None else now
        entries = self.refresh() if entries is None else entries
        removed = []
        with self._lock:
            for entry in entries:
                if entry.index in self.pinned:
                    continue
                try:
                    modified = entry.path.stat().st_mtime
                except OSError:
                    self._deleted.add(entry.index)
                    continue
                if now - modified <= self.retention_seconds:
                    break
                entry.path.unlink(missing_ok=True)
                self._deleted.add(entry.index)
                removed.append(entry.path)
            retained = [entry for index, entry in self._entries.items() if index not in self._deleted]
            self.first_start = min((entry.start for entry in retained), default=None)
        return removed
