"""Cross-process rate limiter for Gemini API calls.

Uses an advisory file lock in ``output/.ratelimit/`` keyed by sha256(api_key)[:12]
and sanitized model name to enforce a maximum Requests Per Minute (RPM) across
all concurrent job subprocesses.
"""

import hashlib
import json
import os
import re
import time
from typing import Optional

# Default to 12 RPM (under Google's free-tier limit of 15 RPM to give safety margin)
DEFAULT_MAX_RPM = 12


def _get_lock_dir(base_dir: Optional[str] = None) -> str:
    if base_dir:
        # If passed a specific job output dir (e.g. output/<job_id>), place .ratelimit in parent
        if os.path.basename(base_dir) != "output" and os.path.isdir(os.path.dirname(base_dir)):
            parent = os.path.dirname(base_dir)
            if os.path.basename(parent) == "output":
                target = os.path.join(parent, ".ratelimit")
            else:
                target = os.path.join(base_dir, ".ratelimit")
        else:
            target = os.path.join(base_dir, ".ratelimit")
    else:
        out_dir = os.environ.get("OUTPUT_DIR", "output")
        target = os.path.join(out_dir, ".ratelimit")
    os.makedirs(target, exist_ok=True)
    return target


def _sanitize_slug(val: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', val or "default")[:32]


class _FileLock:
    def __init__(self, path: str):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a+")
        try:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        except ImportError:
            try:
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
            except (ImportError, OSError):
                pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fh is not None:
            try:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            except ImportError:
                try:
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except (ImportError, OSError):
                    pass
            except Exception:
                pass
            try:
                self.fh.close()
            except Exception:
                pass
            self.fh = None


def acquire_gemini_slot(
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    output_dir: Optional[str] = None,
    max_rpm: Optional[int] = None,
) -> float:
    """Acquires a rate limit slot for a Gemini call.

    Sleeps if necessary to stay within `max_rpm` requests per minute.
    Returns the total seconds waited (0.0 if slot was available immediately).
    """
    key = api_key or os.getenv("GEMINI_API_KEY", "default_key")
    key_hash = hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:12]
    model_slug = _sanitize_slug(model_name or os.environ.get("GEMINI_MODEL") or "default")

    if max_rpm is None:
        try:
            max_rpm = max(1, int(os.environ.get("GEMINI_MAX_RPM", str(DEFAULT_MAX_RPM))))
        except ValueError:
            max_rpm = DEFAULT_MAX_RPM

    lock_dir = _get_lock_dir(output_dir)
    lock_file = os.path.join(lock_dir, f"{key_hash}_{model_slug}.lock")
    state_file = os.path.join(lock_dir, f"{key_hash}_{model_slug}.json")

    total_waited = 0.0

    while True:
        wait_needed = 0.0
        with _FileLock(lock_file):
            now = time.time()
            timestamps = []
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            timestamps = [float(t) for t in data if isinstance(t, (int, float))]
                except Exception:
                    timestamps = []

            # Retain only timestamps from the last 60 seconds
            timestamps = [t for t in timestamps if now - t < 60.0]

            if len(timestamps) >= max_rpm:
                # Need to wait until the oldest timestamp exits the 60s window
                oldest = timestamps[0]
                wait_needed = max(0.05, 60.0 - (now - oldest) + 0.1)
            else:
                timestamps.append(now)
                try:
                    with open(state_file, "w", encoding="utf-8") as f:
                        json.dump(timestamps, f)
                except Exception:
                    pass
                return total_waited

        if wait_needed > 0:
            time.sleep(wait_needed)
            total_waited += wait_needed
