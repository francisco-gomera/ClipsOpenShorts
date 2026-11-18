"""Resolve a YouTube Live URL to public media URLs using repository policy."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from security_utils import assert_public_url
from yt_clients import (NotASingleVideo, fallback_extractor_args,
                        youtube_non_video_reason)


class LiveResolveError(RuntimeError):
    """A clear, user-facing failure while resolving a live video."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


_AUTH_REQUIRED_MESSAGE = (
    "YouTube exige iniciar sesión para acceder a este directo, posiblemente por una "
    "restricción de edad o privacidad. Configura YOUTUBE_COOKIES con cookies de una "
    "cuenta autorizada y vuelve a iniciar la sesión."
)


def _requires_youtube_auth(message: str) -> bool:
    text = (message or "").lower()
    markers = (
        "sign in to confirm your age", "age-restricted", "confirm your age",
        "login_required", "private video", "sign in to view this video",
    )
    return any(marker in text for marker in markers)


def _validate_youtube_url(url: str) -> None:
    try:
        parts = urlparse(url)
    except (TypeError, ValueError) as exc:
        raise LiveResolveError("Introduce un enlace válido de YouTube Live.") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not (
        host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    ):
        raise LiveResolveError("El enlace debe pertenecer a YouTube.")
    try:
        assert_public_url(url)
    except Exception as exc:
        raise LiveResolveError("El enlace no es público o no puede verificarse como seguro.") from exc
    reason = youtube_non_video_reason(url)
    if reason:
        raise NotASingleVideo(f"Este enlace no es un video individual: {reason}.")


def _attempts() -> list[tuple[str | None, bool]]:
    """Return direct, static and paid routes; cookie then anonymous per route."""
    routes: list[str | None] = [None]
    routes.extend(p.strip() for p in os.environ.get("STATIC_PROXY_URLS", "").split(",") if p.strip())
    paid = os.environ.get("PROXY_URL", "").strip()
    if paid:
        routes.append(paid)
    return [(route, cookies) for route in routes for cookies in (True, False)]


def _extractor_args() -> dict[str, Any]:
    return fallback_extractor_args(
        os.environ.get("BGUTIL_BASE_URL", "").strip(),
        os.environ.get("BGUTIL_SCRIPT_PATH", "").strip(),
    )


def _select_media(info: dict[str, Any]) -> tuple[str, str | None]:
    """Select the best available <=720p format and separate audio if needed."""
    formats = [f for f in info.get("formats", []) if isinstance(f, dict) and f.get("url")]
    videos = [f for f in formats if f.get("vcodec") not in (None, "none")
              and (f.get("height") or 0) <= 720]
    audios = [f for f in formats if f.get("acodec") not in (None, "none")]
    videos.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    audios.sort(key=lambda f: f.get("abr") or f.get("tbr") or 0, reverse=True)
    video = videos[0] if videos else None
    if video and video.get("acodec") not in (None, "none"):
        return video["url"], None
    if video and audios:
        return video["url"], audios[0]["url"]
    # Manifest URLs can mux audio/video; they are used only when yt-dlp has no
    # separately selectable formats. Exposed URLs are checked before ffmpeg.
    for key in ("url", "manifest_url"):
        if info.get(key):
            return info[key], None
    raise LiveResolveError("YouTube no ofreció un stream de video compatible.")


def resolve_live(url: str, *, ydl_factory=None) -> dict[str, Any]:
    """Resolve a live URL. Every extraction runs inside the repository SSRF guard."""
    _validate_youtube_url(url)
    if ydl_factory is None:
        import yt_dlp
        ydl_factory = yt_dlp.YoutubeDL
    errors: list[str] = []
    static_errors: list[str] = []
    paid_proxy = os.environ.get("PROXY_URL", "").strip()
    for proxy, cookies in _attempts():
        cookie_file = None
        is_paid = bool(paid_proxy and proxy == paid_proxy)
        if is_paid:
            # Match cloud/metering's established rule: the per-GB route is
            # reached only when a static route failed for an IP-specific cause.
            try:
                from cloud.metering import static_failure_warrants_paid
                if not static_errors or not any(static_failure_warrants_paid(e) for e in static_errors):
                    break
            except Exception:
                break
        cookie_blob = os.environ.get("YOUTUBE_COOKIES", "") if cookies else ""
        try:
            if cookie_blob:
                # yt-dlp's Mozilla cookie jar requires the Netscape header.
                # People commonly paste only the tab-separated rows into .env,
                # so restore the header without changing the stored secret.
                cookie_blob = cookie_blob.lstrip("\ufeff")
                if not cookie_blob.lstrip().startswith("# Netscape HTTP Cookie File"):
                    cookie_blob = "# Netscape HTTP Cookie File\n" + cookie_blob.lstrip("\r\n")
                # Unique per-call file; never log cookie contents or race sessions.
                cookie_dir = os.environ.get("LIVE_COOKIE_DIR", "/tmp")
                Path(cookie_dir).mkdir(parents=True, exist_ok=True)
                handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="live-cookies-",
                                                     suffix=".txt", dir=cookie_dir, delete=False)
                cookie_file = Path(handle.name)
                with handle:
                    handle.write(cookie_blob)
            opts = {
                "quiet": True, "no_warnings": True, "noplaylist": True,
                "skip_download": True, "socket_timeout": 30, "retries": 2,
                "fragment_retries": 2, "cachedir": False,
                "format": "best[height<=720]/bv*[height<=720]+ba/b",
                "extractor_args": _extractor_args(), "proxy": proxy,
                "cookiefile": str(cookie_file) if cookie_file else None,
            }
            import ssrf_guard
            with ssrf_guard.guarded(), ydl_factory(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise LiveResolveError("No se pudo leer la información del directo.")
            status = str(info.get("live_status") or "").lower()
            is_live = bool(info.get("is_live")) or status == "is_live"
            if not is_live:
                if status in ("is_upcoming", "upcoming", "was_upcoming"):
                    return {"state": "programado", "title": info.get("title", "Directo"),
                            "channel": info.get("channel") or info.get("uploader"),
                            "id": info.get("id"), "video_url": None, "audio_url": None}
                return {"state": "no_en_vivo", "title": info.get("title", "Directo"),
                        "channel": info.get("channel") or info.get("uploader"),
                        "id": info.get("id"), "video_url": None, "audio_url": None}
            video_url, audio_url = _select_media(info)
            assert_public_url(video_url)
            if audio_url:
                assert_public_url(audio_url)
            return {
                "state": "en_vivo", "title": info.get("title", "Directo"),
                "channel": info.get("channel") or info.get("uploader"),
                "id": info.get("id"), "video_url": video_url,
                "audio_url": audio_url, "proxy": "direct" if proxy is None else "proxy",
            }
        except LiveResolveError:
            raise
        except Exception as exc:
            error_text = str(exc)
            if _requires_youtube_auth(error_text):
                raise LiveResolveError(_AUTH_REQUIRED_MESSAGE, retryable=False) from None
            errors.append(error_text)
            if proxy is not None and not is_paid:
                static_errors.append(str(exc))
        finally:
            if cookie_file:
                try:
                    cookie_file.unlink(missing_ok=True)
                except OSError:
                    pass
    raise LiveResolveError("No se pudo resolver el directo. Comprueba el enlace y vuelve a intentarlo.") from None
