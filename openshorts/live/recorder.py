"""Supervised ffmpeg HLS/HTTP stream segment recorder."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .config import SEGMENT_SECONDS


class StreamRecorder:
    def __init__(self, directory: str | Path, *, segment_seconds: int = SEGMENT_SECONDS,
                 ffmpeg: str = "ffmpeg", popen=subprocess.Popen):
        self.directory = Path(directory)
        self.segment_seconds = max(2, int(segment_seconds))
        self.ffmpeg = ffmpeg
        self._popen = popen
        self.process = None
        self.next_number = 0
        self._supervisor_thread = None
        self._stop_event = threading.Event()

    def build_command(self, video_url: str, audio_url: str | None = None) -> list[str]:
        self.directory.mkdir(parents=True, exist_ok=True)
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
               "-reconnect", "1", "-reconnect_streamed", "1",
               "-reconnect_delay_max", "10", "-i", video_url]
        audio_input = None
        if audio_url:
            audio_input = "1:a:0"
            cmd += ["-reconnect", "1", "-reconnect_streamed", "1",
                    "-reconnect_delay_max", "10", "-i", audio_url]
        cmd += ["-map", "0:v:0"]
        cmd += ["-map", audio_input or "0:a:0?"]
        cmd += ["-c", "copy", "-f", "segment", "-segment_time", str(self.segment_seconds),
                "-segment_format", "mpegts", "-reset_timestamps", "1",
                "-segment_start_number", str(self.next_number),
                "-segment_list", str(self.directory / f"segments_{self.next_number:06d}.csv"),
                "-segment_list_type", "csv", str(self.directory / "seg_%06d.ts")]
        return cmd

    def start(self, video_url: str, audio_url: str | None = None):
        if self.process and self.process.poll() is None:
            raise RuntimeError("El grabador ya está activo")
        cmd = self.build_command(video_url, audio_url)
        self.process = self._popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        return self.process

    def stop(self, timeout: float = 8.0) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGINT)
        except (AttributeError, ProcessLookupError, PermissionError, OSError):
            process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (AttributeError, ProcessLookupError, PermissionError, OSError):
                process.kill()
            process.wait(timeout=3)

    def restart(self, video_url: str, audio_url: str | None = None):
        """Continue segment numbering after a failed capture process."""
        self.stop()
        from .buffer import SegmentBuffer
        entries = SegmentBuffer(self.directory).refresh()
        self.next_number = max((e.index for e in entries), default=-1) + 1
        return self.start(video_url, audio_url)

    def supervise(self, url: str, *, resolve, on_state=None, retry_min: float = 2.0,
                  retry_max: float = 30.0, sleep=time.sleep):
        """Run capture with re-resolution and bounded backoff after disconnects.

        `resolve(url)` must return a resolver result. Upcoming streams are
        polled until they start; terminal non-live results end the session.
        """
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            raise RuntimeError("El supervisor del grabador ya está activo")
        self._stop_event.clear()

        def report(state, **extra):
            if on_state:
                on_state(state, extra)

        def loop():
            delay = max(0.1, retry_min)
            try:
                while not self._stop_event.is_set():
                    try:
                        info = resolve(url)
                        state = info.get("state")
                        if state == "no_en_vivo":
                            report("finalizando", reason="no_en_vivo")
                            return
                        if state == "programado":
                            report("esperando", title=info.get("title"))
                            self._stop_event.wait(delay)
                            delay = min(max(delay * 1.5, retry_min), retry_max)
                            continue
                        if state != "en_vivo":
                            raise RuntimeError("El resolver devolvió un estado desconocido")
                        self.start(info["video_url"], info.get("audio_url"))
                        report("capturando", title=info.get("title"), id=info.get("id"))
                        delay = max(0.1, retry_min)
                        while not self._stop_event.wait(0.5):
                            if self.process.poll() is not None:
                                break
                        if self._stop_event.is_set():
                            return
                        report("reconectando")
                    except Exception as exc:
                        if self._stop_event.is_set():
                            return
                        if getattr(exc, "retryable", True) is False:
                            report("error", error=str(exc))
                            return
                        report("reconectando", error=type(exc).__name__)
                    self._stop_event.wait(delay)
                    delay = min(max(delay * 2, retry_min), retry_max)
            finally:
                self.stop()

        self._supervisor_thread = threading.Thread(target=loop, name="live-recorder", daemon=True)
        self._supervisor_thread.start()
        return self._supervisor_thread

    def stop_supervisor(self, timeout: float = 15.0) -> None:
        self._stop_event.set()
        self.stop()
        thread = self._supervisor_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)
