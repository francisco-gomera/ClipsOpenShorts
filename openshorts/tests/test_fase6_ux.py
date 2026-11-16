import os
import json
import uuid
import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app, jobs


@pytest.fixture
def client():
    return TestClient(app)


def test_projects_endpoint_returns_expected_structure(tmp_path, monkeypatch):
    """Verify /api/projects returns the structured list expected by the recent projects component."""
    out_root = tmp_path / "output"
    out_root.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))

    job1_id = "11111111-1111-4111-8111-111111111111"
    job2_id = "22222222-2222-4222-8222-222222222222"

    job1_dir = out_root / job1_id
    job1_dir.mkdir()
    meta1 = {
        "title": "First Project",
        "created_at": "2026-11-15T10:00:00Z",
        "shorts": [{"video_url": "clip1.mp4"}],
    }
    (job1_dir / "project_metadata.json").write_text(json.dumps(meta1))

    job2_dir = out_root / job2_id
    job2_dir.mkdir()
    meta2 = {
        "title": "Second Project",
        "created_at": "2026-11-16T10:00:00Z",
        "shorts": [{"video_url": "clip2.mp4"}, {"video_url": "clip3.mp4"}],
    }
    (job2_dir / "project_metadata.json").write_text(json.dumps(meta2))

    test_client = TestClient(app)
    resp = test_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert "projects" in data
    assert isinstance(data["projects"], list)
    assert len(data["projects"]) >= 2

    # Check project metadata contains required fields
    p_ids = [p.get("job_id") or p.get("id") for p in data["projects"]]
    assert job1_id in p_ids
    assert job2_id in p_ids


def test_project_restore_endpoint(tmp_path, monkeypatch):
    """Verify /api/projects/{job_id}/restore restores the job into memory for one-click reopening."""
    job_id = "33333333-3333-4333-8333-333333333333"
    out_root = tmp_path / "output"
    job_dir = out_root / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))

    meta = {
        "title": "Restorable Project",
        "status": "completed",
        "shorts": [{"start": 10.0, "end": 25.0, "video_url": f"/videos/{job_id}/clip1.mp4"}],
        "source_video": "source.mp4",
    }
    (job_dir / "project_metadata.json").write_text(json.dumps(meta))
    (job_dir / "source.mp4").write_bytes(b"\x00" * 1024)

    test_client = TestClient(app)
    resp = test_client.post(f"/api/projects/{job_id}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["has_source"] is True

    # Verify job is present in in-memory jobs dictionary
    assert job_id in jobs
