import os
import json
import asyncio
import httpx
import pytest

app_module = pytest.importorskip("app")


def _request(method, path, json_body=None):
    async def _do():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)
    return asyncio.run(_do())


def test_status_endpoint_includes_stages(tmp_path, monkeypatch):
    out_root = tmp_path / "output"
    up_root = tmp_path / "uploads"
    job_dir = out_root / "status_test_job"
    job_dir.mkdir(parents=True)
    up_root.mkdir(parents=True)

    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(up_root))

    meta = {
        "shorts": [{"index": 0, "start": 0, "end": 15}],
        "transcript": {"segments": [{"start": 0, "end": 15, "text": "test"}]},
    }
    (job_dir / "meta_metadata.json").write_text(json.dumps(meta))
    (job_dir / "clip_1.mp4").write_bytes(b"clip")

    app_module.jobs["status_test_job"] = {
        "status": "completed",
        "logs": app_module._TimedLog(["done"]),
        "result": {"clips": []},
        "user_id": None,
    }

    resp = _request("GET", "/api/status/status_test_job")
    assert resp.status_code == 200
    data = resp.json()
    assert "stages" in data
    assert "stages" in data["stages"]
    assert data["stages"]["stages"]["transcription"]["status"] == "completed"


def test_retry_endpoint(tmp_path, monkeypatch):
    out_root = tmp_path / "output"
    up_root = tmp_path / "uploads"
    job_id = "e1a82c34-8c09-4d6b-b4a1-0987654321ab"
    job_dir = out_root / job_id
    job_dir.mkdir(parents=True)
    up_root.mkdir(parents=True)

    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(up_root))

    # Video en uploads
    src = up_root / f"{job_id}_input.mp4"
    src.write_bytes(b"content")

    # Transcript checkpoint
    (job_dir / ".transcript_checkpoint.json").write_text(json.dumps({
        "transcript": {"segments": [{"start": 0, "end": 10, "text": "words"}]}
    }))

    app_module.jobs[job_id] = {
        "status": "failed",
        "logs": app_module._TimedLog(["failed"]),
        "user_id": None,
        "cmd": ["python", "main.py", "-i", str(src)],
    }

    resp = _request("POST", f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "queued"
    assert app_module.jobs[job_id]["status"] == "queued"
    assert "--transcript" in app_module.jobs[job_id]["cmd"]
