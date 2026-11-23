"""Child process entry point for one live clipping session."""
from __future__ import annotations

import os
import signal
import sys

from live.session import LiveSessionRuntime


def main() -> int:
    session_id = os.environ.get("LIVE_SESSION_ID", "")
    url = os.environ.get("LIVE_URL", "")
    output_dir = os.environ.get("LIVE_OUTPUT_DIR", "")
    stop_file = os.environ.get("LIVE_STOP_FILE", "")
    if not all((session_id, url, output_dir, stop_file)):
        print("LIVE_WORKER_ERROR configuración incompleta", file=sys.stderr, flush=True)
        return 2
    def request_controlled_stop(_signum, _frame):
        try:
            with open(stop_file, "w", encoding="utf-8") as handle:
                handle.write("detener_ya")
        except OSError:
            pass

    signal.signal(signal.SIGTERM, request_controlled_stop)
    signal.signal(signal.SIGINT, request_controlled_stop)
    try:
        LiveSessionRuntime(session_id, url, output_dir, stop_file).run()
        return 0
    except Exception as exc:
        print(f"LIVE_WORKER_ERROR {type(exc).__name__}: {str(exc)[:300]}",
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
