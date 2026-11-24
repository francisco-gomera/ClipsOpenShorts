"""Optional text-only LLM metadata judge with a deterministic fallback."""
from __future__ import annotations

import os
import threading

from .config import LLM_TIMEOUT

_LLM_LOCK = threading.Lock()


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

        return DetailClipFallback


def _transcript_context(transcript: dict, start: float, end: float, margin: float = 15.0) -> str:
    selected = [item for item in transcript.get("segments", [])
                if float(item.get("end", 0)) >= start - margin
                and float(item.get("start", 0)) <= end + margin]
    timed_words = [word for item in selected for word in item.get("words", [])
                   if float(word.get("end", 0)) >= start - margin
                   and float(word.get("start", 0)) <= end + margin]
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


def _fallback(candidate: dict, text: str) -> dict:
    clean = " ".join(text.split())
    hook = " ".join(clean.split()[:8]).strip(" .,!?:;") or candidate.get("why", "Momento destacado")
    title = hook[:90] or "Momento destacado del directo"
    return {
        "start": float(candidate["start"]), "end": float(candidate["end"]),
        "id": str(candidate.get("id", "live")),
        "source_window_id": str(candidate.get("id", "live")),
        "min_clip_seconds": int(candidate.get("min_clip_seconds", 30)),
        "max_clip_seconds": int(candidate.get("max_clip_seconds", 60)),
        "predicted_score": int(candidate.get("predicted_score", 50)),
        "video_description_for_tiktok": f"{hook} #directo #shorts",
        "video_description_for_instagram": f"{hook} #reels",
        "video_title_for_youtube_short": title, "viral_hook_text": hook,
        "why": candidate.get("why", "Momento destacado del directo"),
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
                return fallback
        except Exception:
            return fallback
    try:
        DetailClipModel = _detail_schema()
        no_think = " /no_think" if os.environ.get("LLM_THINK", "0").strip() in ("0", "false", "False") else ""
        prompt = f"""Analiza el siguiente momento de un directo y devuelve JSON con el esquema.
Escribe en español cuando el texto esté en español. Puntúa el potencial de 0 a 100.
No inventes hechos. El hook debe ser breve. Conserva exactamente estos tiempos y source_window_id.
Tiempos: {candidate['start']:.3f}–{candidate['end']:.3f}
Duración configurada para esta sesión: {fallback['min_clip_seconds']}–{fallback['max_clip_seconds']} segundos.
source_window_id: {candidate.get('id', 'live')}
Señales: {', '.join(candidate.get('signals', []))}; razón: {candidate.get('why', '')}
Transcripción con contexto:{no_think}
{text[:6000]}
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
        parsed["start"] = fallback["start"]
        parsed["end"] = fallback["end"]
        parsed["source_window_id"] = fallback["source_window_id"]
        parsed["id"] = fallback["id"]
        parsed["min_clip_seconds"] = fallback["min_clip_seconds"]
        parsed["max_clip_seconds"] = fallback["max_clip_seconds"]
        parsed.setdefault("why", fallback["why"])
        components = []
        if "audio" in candidate.get("signals", []):
            components.append((0.45, min(1.0, float(candidate.get("audio_z", 0)) / 6.0)))
        if "keyword" in candidate.get("signals", []):
            components.append((0.20, float(candidate.get("keyword_score", 0))))
        components.append((0.35, max(0.0, min(100.0, float(parsed.get("predicted_score", 0)))) / 100.0))
        total_weight = sum(weight for weight, _ in components)
        parsed["predicted_score"] = round(100 * sum(weight * value for weight, value in components) / total_weight)
        return parsed
    except Exception:
        return fallback
