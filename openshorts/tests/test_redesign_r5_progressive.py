"""
Rediseño R5 — Progressive Clip Display & Real Progress
======================================================
Verifica los requisitos de progreso verificable y entrega progresiva de clips:
  1. App.jsx:
     - Renderiza ClipSkeletonCard para los clips pendientes mientras se procesan.
     - Calcula pendingClips deduciendo los clips ya listos en results.clips.
     - Cuando no hay clips listos aún, muestra estado claro 'Analyzing video moments...'.
  2. ClipProgressCard.jsx:
     - Gestiona substages ('cut', 'reframe', 'hook', 'subtitles', 'done').
     - Muestra estado 'Listo' / badge verde para clips finalizados y % real para los que están en curso.
  3. app.py / Backend:
     - /api/status/{job_id} expone 'clips', 'counters' y 'result' incremental conforme se reciben marcadores CLIP_READY.
"""

import json
import os
import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app, jobs


DASHBOARD_SRC = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "src"
)
APP_JSX = os.path.join(DASHBOARD_SRC, "App.jsx")
CLIP_PROGRESS_CARD_JSX = os.path.join(
    DASHBOARD_SRC, "components", "processing", "ClipProgressCard.jsx"
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. Frontend: App.jsx Progressive Display
# ---------------------------------------------------------------------------

def test_app_jsx_defines_clip_skeleton_card():
    """App.jsx defines ClipSkeletonCard for in-flight clip rendering."""
    src = _read(APP_JSX)
    assert "function ClipSkeletonCard" in src
    assert "Processing vertical clip" in src
    assert "Trimming fragment..." in src
    assert "Reframing 9:16..." in src


def test_app_jsx_computes_pending_clips():
    """App.jsx filters out completed clips from stages.clips to avoid duplicate cards."""
    src = _read(APP_JSX)
    assert "pendingClips" in src
    assert "stages?.clips" in src
    assert "readyIndices" in src


def test_app_jsx_renders_skeletons_alongside_ready_clips():
    """In the results grid, App.jsx renders ResultCard for ready clips and ClipSkeletonCard for pending ones."""
    src = _read(APP_JSX)
    assert "pendingClips.map" in src
    assert "<ClipSkeletonCard" in src
    assert "Analyzing video moments..." in src


# ---------------------------------------------------------------------------
# 2. Frontend: ClipProgressCard
# ---------------------------------------------------------------------------

def test_clip_progress_card_substages():
    """ClipProgressCard contains defined substage keys."""
    src = _read(CLIP_PROGRESS_CARD_JSX)
    for sub in ('cut', 'reframe', 'hook', 'subtitles', 'done'):
        assert sub in src, f"Substage {sub} missing in ClipProgressCard.jsx"
    assert "isReady" in src
    assert "Listo" in src


# ---------------------------------------------------------------------------
# 3. Backend: /api/status/{job_id} Incremental Results
# ---------------------------------------------------------------------------

def test_api_status_delivers_incremental_ready_clips(tmp_path, monkeypatch):
    """When a job is running and ready_files are registered, /api/status returns
    the completed clips incrementally in data.result while the job is still processing."""
    out_root = tmp_path / "output"
    out_root.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))

    job_id = "55555555-5555-4555-8555-555555555555"
    job_dir = out_root / job_id
    job_dir.mkdir()

    # Create dummy rendered clip file on disk
    clip1_name = "test_clip_1.mp4"
    (job_dir / clip1_name).write_bytes(b"\x00" * 2048)

    # Register in in-memory jobs with 1 ready file while status is still 'processing'
    jobs[job_id] = {
        'id': job_id,
        'status': 'processing',
        'logs': ['Processing clip 1...'],
        'ready_files': {0: clip1_name},
        'result': {
            'clips': [
                {
                    'start': 0.0,
                    'end': 15.0,
                    'video_title_for_youtube_short': 'First Ready Clip',
                    'video_url': f"/videos/{job_id}/{clip1_name}",
                }
            ],
            'cost_analysis': None,
        },
        'stages': {
            'status': 'processing',
            'percent': 50.0,
            'mode': 'determinate',
            'stage_index': 5,
            'stage_total': 6,
            'current_stage': 'cut_and_reframe',
            'clips': [
                {'index': 0, 'status': 'completed', 'ready': True, 'percent': 100.0},
                {'index': 1, 'status': 'processing', 'ready': False, 'percent': 40.0, 'substage': 'reframe'},
            ],
            'counters': {'total': 2, 'ready': 1, 'failed': 0},
        },
    }

    client = TestClient(app)
    resp = client.get(f"/api/status/{job_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "processing"
    # Result contains the 1 ready clip
    assert data["result"] is not None
    assert len(data["result"]["clips"]) == 1
    assert data["result"]["clips"][0]["video_title_for_youtube_short"] == "First Ready Clip"

    # Stages contains 2 clips (1 ready, 1 in-flight)
    assert len(data["stages"]["clips"]) == 2
    assert data["stages"]["counters"]["ready"] == 1
    assert data["stages"]["counters"]["total"] == 2
