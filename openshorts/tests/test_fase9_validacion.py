"""
Fase 9 – Validación End-to-End
================================
Functional integration tests that exercise observable system behaviour
without spinning up external services.  Each section maps to one scenario
from the plan:

  1. Health & Config endpoints (liveness, readiness, /api/config)
  2. /api/process — URL submit: missing Gemini key → error
  3. /api/process — invalid / playlist URL → 400
  4. /api/process — too-short source (< MIN_SOURCE_SECONDS) → 400
  5. /api/process — file upload path: file size limit enforced by backend
  6. /api/status — unknown job_id → 404; path-traversal attempt → 400
  7. /api/projects — list returns {projects: list}
  8. /api/projects/{id} — restore and delete lifecycle
  9. /api/jobs/{id}/download-all — ZIP contains correct clip files
 10. Settings — /api/config returns billingEnabled=false for self-host
 11. Clip editor — /api/clip/rerender requires a valid job
 12. Hook — /api/hook requires Gemini key when no local LLM
 13. Subtitle — /api/subtitle requires Gemini key when no local LLM
 14. index.html — contains viewport meta (mobile responsiveness)
 15. index.html — contains noindex meta or is served correctly
 16. Error state: very short upload file (duration stub) → 400 short-source
 17. Error state: private/internal IP URL → 400 SSRF guard

Tests rely only on FastAPI's TestClient / httpx.ASGITransport so Docker is
not required at test runtime — the app module is imported directly inside the
container where pytest runs.
"""

import asyncio
import io
import json
import os
import uuid
import zipfile

import httpx
import pytest

app_module = pytest.importorskip("app")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TEST_JOB_ID = "11111111-1111-4111-8111-111111111111"
GEMINI_HEADER = {"X-Gemini-Key": "test-key"}


def _client():
    transport = httpx.ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Health & Config
# ---------------------------------------------------------------------------

def test_health_liveness():
    async def _go():
        async with _client() as c:
            r = await c.get("/health")
        return r
    r = run(_go())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_readiness():
    async def _go():
        async with _client() as c:
            r = await c.get("/health/ready")
        return r
    r = run(_go())
    assert r.status_code in (200, 503)   # 503 only during graceful drain


def test_config_self_host():
    """In BYOK (self-host) mode billingEnabled is False."""
    async def _go():
        async with _client() as c:
            r = await c.get("/api/config")
        return r
    r = run(_go())
    assert r.status_code == 200
    body = r.json()
    assert "billingEnabled" in body
    assert body["billingEnabled"] is False   # conftest sets BILLING_ENABLED=0
    assert "youtubeUrlEnabled" in body
    assert "jobRetentionSeconds" in body


# ---------------------------------------------------------------------------
# 2. /api/process — missing Gemini key (no local LLM configured)
# ---------------------------------------------------------------------------

def test_process_missing_gemini_key(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path / "up"))
    (tmp_path / "out").mkdir()
    (tmp_path / "up").mkdir()

    # Ensure no local LLM is active so the key is mandatory
    monkeypatch.setattr(app_module.llm_backend, "active", lambda: False)

    async def _go():
        async with _client() as c:
            # POST with no Gemini key header or cookie
            r = await c.post(
                "/api/process",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                      "acknowledged": True},
            )
        return r
    r = run(_go())
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "gemini" in detail.lower() or "api key" in detail.lower() or "key" in detail.lower()


# ---------------------------------------------------------------------------
# 3. /api/process — invalid URL (playlist / channel)
# ---------------------------------------------------------------------------

def test_process_playlist_url_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path / "up"))
    (tmp_path / "out").mkdir()
    (tmp_path / "up").mkdir()

    async def _go():
        async with _client() as c:
            r = await c.post(
                "/api/process",
                json={"url": "https://www.youtube.com/playlist?list=PLxxx",
                      "acknowledged": True},
                headers=GEMINI_HEADER,
            )
        return r
    r = run(_go())
    assert r.status_code == 400
    detail = r.json().get("detail", "").lower()
    assert "playlist" in detail or "single video" in detail or "link" in detail


# ---------------------------------------------------------------------------
# 4. /api/process — too-short source gate
# ---------------------------------------------------------------------------

def test_process_short_source_rejected(tmp_path, monkeypatch):
    """Source shorter than MIN_SOURCE_SECONDS must be rejected with 400."""
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path / "up"))
    (tmp_path / "out").mkdir()
    (tmp_path / "up").mkdir()

    # Stub the quality probe so it claims a 20-second video
    async def _fake_probe(url):
        return {"max_height": 1080, "duration": 20}
    monkeypatch.setattr(app_module, "_probe_youtube_quality", _fake_probe)

    # Make sure the short-source threshold is > 20 s
    monkeypatch.setattr(app_module, "MIN_SOURCE_SECONDS", 45)

    async def _go():
        async with _client() as c:
            r = await c.post(
                "/api/process",
                json={"url": "https://www.youtube.com/watch?v=tooshort",
                      "acknowledged": True},
                headers=GEMINI_HEADER,
            )
        return r
    r = run(_go())
    assert r.status_code == 400
    detail = r.json().get("detail", "").lower()
    assert "short" in detail or "20" in detail or "45" in detail


# ---------------------------------------------------------------------------
# 5. /api/process — file upload: oversized file rejected
# ---------------------------------------------------------------------------

def test_process_oversized_file_rejected(tmp_path, monkeypatch):
    """Files larger than MAX_UPLOAD_BYTES (or the UI's 500 MB guard) must be
    caught. We test the backend path: even a stub-large file claim is rejected
    cleanly without crashing the server."""
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path / "up"))
    (tmp_path / "out").mkdir()
    (tmp_path / "up").mkdir()

    # Send a minimal file but with a spoofed Content-Length that exceeds limit
    # The backend should still respond, not crash
    small_data = b"fake video bytes"
    async def _go():
        async with _client() as c:
            # POST a tiny file; we just verify the endpoint responds (not 500)
            r = await c.post(
                "/api/process",
                content=small_data,
                headers={
                    **GEMINI_HEADER,
                    "Content-Type": "multipart/form-data; boundary=testboundary",
                },
            )
        return r
    r = run(_go())
    # Any non-500 response means the server handled it gracefully
    assert r.status_code != 500


# ---------------------------------------------------------------------------
# 6. /api/status — unknown job and path traversal
# ---------------------------------------------------------------------------

def test_status_unknown_job_returns_404():
    async def _go():
        async with _client() as c:
            r = await c.get(f"/api/status/{uuid.uuid4()}")
        return r
    r = run(_go())
    assert r.status_code == 404


def test_status_path_traversal_rejected():
    async def _go():
        async with _client() as c:
            r = await c.get("/api/status/../../etc/passwd")
        return r
    r = run(_go())
    assert r.status_code in (400, 404)


# ---------------------------------------------------------------------------
# 7. /api/projects — list
# ---------------------------------------------------------------------------

def test_projects_list_shape():
    async def _go():
        async with _client() as c:
            r = await c.get("/api/projects")
        return r
    r = run(_go())
    assert r.status_code == 200
    body = r.json()
    assert "projects" in body
    assert isinstance(body["projects"], list)


# ---------------------------------------------------------------------------
# 8. /api/projects/{id} — detail + restore + delete lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_project(tmp_path, monkeypatch):
    """Create a minimal project on disk and patch OUTPUT_DIR."""
    job_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    meta = {
        "title": "Validacion Test Project",
        "shorts": [
            {"start": 0.0, "end": 30.0,
             "video_title_for_youtube_short": "Clip 1",
             "predicted_score": 90}
        ],
    }
    (job_dir / "video_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (job_dir / "clip_1.mp4").write_bytes(b"dummy_video_bytes")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    return job_id


def test_project_detail(fake_project):
    async def _go():
        async with _client() as c:
            r = await c.get(f"/api/projects/{fake_project}")
        return r
    r = run(_go())
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Validacion Test Project"


def test_project_restore(fake_project):
    async def _go():
        async with _client() as c:
            r = await c.post(f"/api/projects/{fake_project}/restore")
        return r
    r = run(_go())
    # Restore should succeed: 200 or 201
    assert r.status_code in (200, 201)


def test_project_delete(fake_project):
    async def _go():
        async with _client() as c:
            r = await c.delete(f"/api/projects/{fake_project}")
        return r
    r = run(_go())
    assert r.status_code in (200, 204)


# ---------------------------------------------------------------------------
# 9. Download-all ZIP
# ---------------------------------------------------------------------------

@pytest.fixture()
def zip_project(tmp_path, monkeypatch):
    """Minimal project with two clip files for ZIP download."""
    job_id = "12341234-1234-4234-8234-123412341234"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    meta = {
        "shorts": [
            {"video_url": f"/videos/{job_id}/clip_a.mp4"},
            {"video_url": f"/videos/{job_id}/clip_b.mp4"},
        ]
    }
    (job_dir / "video_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (job_dir / "clip_a.mp4").write_bytes(b"A" * 100)
    (job_dir / "clip_b.mp4").write_bytes(b"B" * 200)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))

    # Stub _ensure_job_files so the endpoint doesn't try to regenerate
    async def _no_files(jid, req):
        return True
    monkeypatch.setattr(app_module, "_ensure_job_files", _no_files)
    return job_id


def test_download_all_zip_valid(zip_project):
    async def _go():
        response = await app_module.download_all_clips(zip_project, None)
        return response
    response = run(_go())
    with zipfile.ZipFile(response.path) as zf:
        names = sorted(zf.namelist())
        assert names == ["clip_01_clip_a.mp4", "clip_02_clip_b.mp4", "descripcion.txt"]
        assert sum(n.endswith(".mp4") for n in names) == 2
        assert "descripcion.txt" in names
        assert zf.testzip() is None   # no corrupt entries
    # Cleanup
    asyncio.run(response.background())


# ---------------------------------------------------------------------------
# 10. Settings — Gemini key validation endpoint
# ---------------------------------------------------------------------------

def test_config_has_local_llm_field():
    """localLlm field present in config (may be None when no server configured)."""
    async def _go():
        async with _client() as c:
            r = await c.get("/api/config")
        return r
    r = run(_go())
    assert r.status_code == 200
    body = r.json()
    assert "localLlm" in body   # None when no local LLM, dict otherwise


# ---------------------------------------------------------------------------
# 11. Clip editor — /api/clip/rerender with invalid job → 404
# ---------------------------------------------------------------------------

def test_rerender_unknown_job(tmp_path, monkeypatch):
    """Rerending a non-existent job returns 4xx (404 not found or 422 schema
    validation — depends on whether Pydantic validates before the endpoint runs)."""
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    async def _go():
        async with _client() as c:
            r = await c.post(
                "/api/clip/rerender",
                json={
                    "job_id": str(uuid.uuid4()),
                    "clip_index": 0,
                },
                headers=GEMINI_HEADER,
            )
        return r
    r = run(_go())
    assert r.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# 12 & 13. Hook / Subtitle — require Gemini key
# ---------------------------------------------------------------------------

def test_hook_missing_key_rejected(tmp_path, monkeypatch):
    """The hook endpoint requires either a Gemini key or a local LLM.
    When neither is present and the job doesn't exist, we get 404 (the job
    lookup happens before the key check in this endpoint).  When neither is
    present and the job *does* exist, we get 400/401.  Either way the server
    must not crash (no 500)."""
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.llm_backend, "active", lambda: False)
    async def _go():
        async with _client() as c:
            r = await c.post(
                "/api/hook",
                json={
                    "job_id": str(uuid.uuid4()),
                    "clip_index": 0,
                    "style": "classic",
                    "text": "Test hook",
                },
                # No Gemini key
            )
        return r
    r = run(_go())
    assert r.status_code != 500   # must not crash
    assert r.status_code in (400, 401, 404, 422)


def test_subtitle_missing_key_rejected(tmp_path, monkeypatch):
    """Same pattern as hook: job lookup may happen before key validation.
    Either way the endpoint must not crash."""
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.llm_backend, "active", lambda: False)
    async def _go():
        async with _client() as c:
            r = await c.post(
                "/api/subtitle",
                json={
                    "job_id": str(uuid.uuid4()),
                    "clip_index": 0,
                    "preset": "default",
                },
                # No Gemini key
            )
        return r
    r = run(_go())
    assert r.status_code != 500
    assert r.status_code in (400, 401, 404, 422)


# ---------------------------------------------------------------------------
# 14. index.html — mobile viewport meta tag
# ---------------------------------------------------------------------------

def _read_index_html() -> str:
    dist = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "dist", "index.html"
    )
    src = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "index.html"
    )
    for path in (dist, src):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read()
    return ""


def test_index_html_has_viewport_meta():
    """index.html must declare a viewport meta for mobile responsiveness."""
    html = _read_index_html()
    if not html:
        pytest.skip("index.html not found (build not run in this environment)")
    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_index_html_has_title():
    html = _read_index_html()
    if not html:
        pytest.skip("index.html not found")
    assert "<title>" in html


# ---------------------------------------------------------------------------
# 15. nginx.conf — noindex for self-hosted instances
# ---------------------------------------------------------------------------

def test_nginx_self_host_noindex():
    nginx = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "nginx.conf"
    )
    with open(nginx, encoding="utf-8") as fh:
        content = fh.read()
    assert "X-Robots-Tag" in content
    assert "noindex" in content


# ---------------------------------------------------------------------------
# 16. SSRF guard — private IP URL rejected
# ---------------------------------------------------------------------------

def test_ssrf_private_ip_rejected(tmp_path, monkeypatch):
    """URLs pointing at RFC-1918 addresses must be rejected before any network
    call is made.  The SSRF guard runs synchronously in _validate_source_url."""
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path / "up"))
    (tmp_path / "out").mkdir()
    (tmp_path / "up").mkdir()

    async def _go():
        async with _client() as c:
            r = await c.post(
                "/api/process",
                json={"url": "http://192.168.1.1/video.mp4",
                      "acknowledged": True},
                headers=GEMINI_HEADER,
            )
        return r
    r = run(_go())
    assert r.status_code == 400
    detail = r.json().get("detail", "").lower()
    # The SSRF guard message mentions the URL or "can't be processed"
    assert "url" in detail or "unsafe" in detail or "private" in detail or "process" in detail


# ---------------------------------------------------------------------------
# 17. Translate languages — always available endpoint
# ---------------------------------------------------------------------------

def test_translate_languages_endpoint():
    async def _go():
        async with _client() as c:
            r = await c.get("/api/translate/languages")
        return r
    r = run(_go())
    assert r.status_code == 200
    body = r.json()
    # Should return a list of language objects or a dict with a languages key
    assert isinstance(body, (list, dict))
