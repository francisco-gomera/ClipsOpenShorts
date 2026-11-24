"""Optional text-only LLM metadata judge with a deterministic fallback."""
from __future__ import annotations

import os
import logging
import threading
from datetime import datetime, timezone

from .config import LLM_TIMEOUT

_LLM_LOCK = threading.Lock()
_LOGGER = logging.getLogger(__name__)


def _detail_schema():
    try:
        from gemini_worker import DetailClipModel
        return DetailClipModel
    except ImportError:
        # Keeps fake-LLM unit tests lightweight outside the full app image.
        from pydantic import BaseModel

        class DetailClipFallback(BaseModel):
            start: float
            end: float
            source_window_id: str
            predicted_score: int
            video_description_for_tiktok: str
            video_description_for_instagram: str
            video_title_for_youtube_short: str
            viral_hook_text: str
            why: str = ""
            video_description_for_youtube_short: str = ""

        return DetailClipFallback


def _transcript_context(transcript: dict, start: float, end: float, margin: float = 15.0) -> str:
    segments = transcript.get("segments", [])
    timed_words = sorted(
        (word for item in segments for word in item.get("words", [])
         if word.get("start") is not None and word.get("end") is not None),
        key=lambda word: (float(word["start"]), float(word["end"])))
    # Expand only around this candidate, and only when its initial context is
    # sparse. This cannot drift to the beginning of a long broadcast.
    selected_words = []
    for radius in (margin, max(margin, 30.0), max(margin, 60.0)):
        selected_words = [word for word in timed_words
                          if float(word["end"]) >= start - radius
                          and float(word["start"]) <= end + radius]
        if sum(len(str(word.get("word") or "")) for word in selected_words) >= 80:
            break
    selected = [item for item in segments
                if float(item.get("end", 0)) >= start - margin
                and float(item.get("start", 0)) <= end + margin]
    # When Whisper supplies word timestamps, those are authoritative. Never
    # fall back to the text of a session-wide segment in that case.
    if timed_words:
        timed_words = selected_words
    if timed_words:
        tokens = [str(word.get("word") or "") for word in timed_words]
        text = "".join(tokens).strip()
        if len(text) <= 6000:
            return text
        center = (start + end) / 2
        anchor = min(range(len(timed_words)),
                     key=lambda i: abs((float(timed_words[i]["start"])
                                        + float(timed_words[i]["end"])) / 2 - center))
        left = right = anchor
        length = len(tokens[anchor])
        while length < 6000 and (left > 0 or right + 1 < len(tokens)):
            if left > 0:
                left -= 1
                length += len(tokens[left]) + 1
            if length >= 6000:
                break
            if right + 1 < len(tokens):
                right += 1
                length += len(tokens[right]) + 1
        return "".join(tokens[left:right + 1]).strip()
    # Segment-only transcripts are safe only when their timestamps describe a
    # bounded local span. A segment spanning most of a LIVE session has no
    # reliable word-to-time mapping, so using its text would leak unrelated
    # context into every candidate.
    selected = [item for item in selected
                if float(item.get("end", 0)) - float(item.get("start", 0)) <= 120]
    text = " ".join(str(item.get("text") or "") for item in selected).strip()
    if len(text) <= 6000:
        return text
    center = (start + end) / 2
    # Keep the candidate in the middle if a long transcript segment exceeds the prompt budget.
    words = " ".join(str(item.get("text") or "") for item in selected).split()
    if not words:
        return ""
    anchor_time = center
    weighted = []
    for item in selected:
        segment_words = str(item.get("text") or "").split()
        if segment_words:
            weighted.extend((float(item.get("start", 0)), token) for token in segment_words)
    anchor = min(range(len(weighted)), key=lambda i: abs(weighted[i][0] - anchor_time)) if weighted else 0
    left = right = anchor
    parts = [weighted[anchor][1]] if weighted else []
    length = len(parts[0]) if parts else 0
    while weighted and length < 6000 and (left > 0 or right + 1 < len(weighted)):
        if left > 0:
            left -= 1
            token = weighted[left][1]
            parts.insert(0, token)
            length += len(token) + 1
        if length >= 6000:
            break
        if right + 1 < len(weighted):
            right += 1
            token = weighted[right][1]
            parts.append(token)
            length += len(token) + 1
    return " ".join(parts)


def _fallback(candidate: dict, text: str, *, error: str | None = None) -> dict:
    clean = " ".join(text.split())
    hook = " ".join(clean.split()[:8]).strip(" .,!?:;") or "Momento destacado del directo"
    title = hook[:90]
    if clean:
        tiktok = f"{hook} #directo #shorts"
        instagram = f"Un momento del directo: {hook}. #reels"
        youtube_description = f"{clean[:400]}\n\n#shorts"
    else:
        tiktok = "Clip del directo. #directo #shorts"
        instagram = "Un momento del directo para compartir. #reels"
        youtube_description = "Un clip del directo.\n\n#shorts"
    now = datetime.now(timezone.utc).isoformat()
    return {
        "start": float(candidate["start"]), "end": float(candidate["end"]),
        "id": str(candidate.get("id", "live")),
        "source_window_id": str(candidate.get("id", "live")),
        "min_clip_seconds": int(candidate.get("min_clip_seconds", 30)),
        "max_clip_seconds": int(candidate.get("max_clip_seconds", 60)),
        "predicted_score": int(candidate.get("predicted_score", 50)),
        "video_description_for_tiktok": tiktok,
        "video_description_for_instagram": instagram,
        "video_title_for_youtube_short": title, "viral_hook_text": hook,
        "video_description_for_youtube_short": youtube_description,
        "metadata_source": "fallback",
        "metadata_error": error or ("transcripcion_insuficiente" if not clean else None),
        "metadata_generated_at": now,
        "metadata_context_start": float(candidate["start"]) - 15.0,
        "metadata_context_end": float(candidate["end"]) + 15.0,
        "why": candidate.get("why", "Momento destacado del directo") if clean
               else "No hay transcripción suficiente para describir este momento.",
    }


def _gemini_generate(prompt, schema, *, model=None, timeout=LLM_TIMEOUT):
    """One bounded text-only Gemini call when no local endpoint is configured."""
    from google import genai
    from google.genai import types
    import gemini_worker
    import gemini_ratelimit

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("No hay proveedor LLM configurado")
    model = model or os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    gemini_ratelimit.acquire_gemini_slot(api_key, model)
    client = genai.Client(api_key=api_key,
                          http_options=types.HttpOptions(timeout=max(1, int(timeout * 1000))))
    response = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_schema=schema))
    gemini_worker.raise_if_blocked(response)
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        parsed = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
    else:
        parsed = gemini_worker._parse_json_response_text(gemini_worker._get_response_text(response))
    return parsed, gemini_worker._calculate_cost_analysis(response, model)


def judge_candidate(candidate: dict, transcript: dict, *, generate=None,
                    timeout: int = LLM_TIMEOUT) -> dict:
    """Return DetailClipModel-shaped metadata; LLM failures never block capture."""
    text = _transcript_context(transcript, float(candidate["start"]), float(candidate["end"]))
    fallback = _fallback(candidate, text)
    if generate is None:
        try:
            import llm_backend
            if llm_backend.active():
                generate = llm_backend.generate_json
            elif os.environ.get("GEMINI_API_KEY"):
                generate = _gemini_generate
            else:
                fallback["metadata_error"] = "proveedor_llm_no_configurado"
                return fallback
        except Exception as exc:
            fallback["metadata_error"] = f"configuracion_llm: {type(exc).__name__}: {exc}"[:500]
            _LOGGER.warning("LIVE metadata fallback for %s: %s", candidate.get("id"),
                            fallback["metadata_error"])
            return fallback
    try:
        DetailClipModel = _detail_schema()
        no_think = " /no_think" if os.environ.get("LLM_THINK", "0").strip() in ("0", "false", "False") else ""
        prompt = f"""Analiza exclusivamente este fragmento temporal del directo y devuelve un objeto JSON válido.
Escribe en español cuando la transcripción esté en español. Puntúa el potencial de 0 a 100.
No inventes nombres, hechos ni acontecimientos. No uses el inicio del directo ni otros clips.
Genera metadatos fundamentados en estas palabras y para este momento concreto.
Los campos son independientes: hook breve; descripción TikTok breve con hashtags pertinentes;
descripción Instagram con estilo propio; título claro de YouTube Shorts (máximo 100 caracteres);
y descripción de YouTube Shorts separada del título y de TikTok.
Conserva exactamente estos tiempos y source_window_id. Devuelve todos los campos del esquema.
Tiempos: {candidate['start']:.3f}–{candidate['end']:.3f}
Duración configurada para esta sesión: {fallback['min_clip_seconds']}–{fallback['max_clip_seconds']} segundos.
source_window_id: {candidate.get('id', 'live')}
Señales: {', '.join(candidate.get('signals', []))}; razón: {candidate.get('why', '')}
Transcripción específica del candidato:{no_think}
<transcripcion_clip>\n{text[:6000]}\n</transcripcion_clip>
"""
        with _LLM_LOCK:
            previous_timeout = os.environ.get("LLM_TIMEOUT")
            os.environ["LLM_TIMEOUT"] = str(timeout)
            try:
                if generate is _gemini_generate:
                    parsed, _cost = generate(prompt, DetailClipModel, timeout=timeout)
                else:
                    parsed, _cost = generate(prompt, DetailClipModel, model=None)
            finally:
                if previous_timeout is None:
                    os.environ.pop("LLM_TIMEOUT", None)
                else:
                    os.environ["LLM_TIMEOUT"] = previous_timeout
        if hasattr(parsed, "model_dump"):
            parsed = parsed.model_dump()
        if not isinstance(parsed, dict):
            raise ValueError("La respuesta de metadatos no es un objeto JSON")
        parsed["start"] = fallback["start"]
        parsed["end"] = fallback["end"]
        parsed["source_window_id"] = fallback["source_window_id"]
        parsed["id"] = fallback["id"]
        parsed["min_clip_seconds"] = fallback["min_clip_seconds"]
        parsed["max_clip_seconds"] = fallback["max_clip_seconds"]
        parsed.setdefault("why", fallback["why"])
        limits = {"video_description_for_tiktok": 2200,
                  "video_description_for_instagram": 2200,
                  "video_title_for_youtube_short": 100,
                  "video_description_for_youtube_short": 5000,
                  "viral_hook_text": 300}
        for key, limit in limits.items():
            value = parsed.get(key)
            if not isinstance(value, str) or not value.strip():
                parsed[key] = fallback[key]
            else:
                parsed[key] = value.strip()[:limit]
        parsed["metadata_source"] = "ai"
        parsed["metadata_error"] = None
        parsed["metadata_generated_at"] = datetime.now(timezone.utc).isoformat()
        parsed["metadata_context_start"] = fallback["metadata_context_start"]
        parsed["metadata_context_end"] = fallback["metadata_context_end"]
        components = []
        if "audio" in candidate.get("signals", []):
            components.append((0.45, min(1.0, float(candidate.get("audio_z", 0)) / 6.0)))
        if "keyword" in candidate.get("signals", []):
            components.append((0.20, float(candidate.get("keyword_score", 0))))
        components.append((0.35, max(0.0, min(100.0, float(parsed.get("predicted_score", 0)))) / 100.0))
        total_weight = sum(weight for weight, _ in components)
        parsed["predicted_score"] = round(100 * sum(weight * value for weight, value in components) / total_weight)
        return parsed
    except Exception as exc:
        fallback["metadata_error"] = f"{type(exc).__name__}: {exc}"[:500]
        _LOGGER.warning("LIVE metadata fallback for %s: %s", candidate.get("id"),
                        fallback["metadata_error"])
        return fallback
