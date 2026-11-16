import os
import json
import time
import pytest
from fastapi.testclient import TestClient

import gemini_worker
import gemini_ratelimit
import transcribe_backends
from app import app, jobs, is_transient_failure, MAX_CONCURRENT_JOBS, AUTO_RETRY_LIMIT, AUTO_RETRY_DELAY_SECONDS


@pytest.fixture
def client():
    return TestClient(app)


def test_parse_retry_delay():
    assert gemini_worker.parse_retry_delay("Please retry in 25.09s.") == 25.09
    assert gemini_worker.parse_retry_delay("Please retry in 25s") == 25.0
    assert gemini_worker.parse_retry_delay("Resource exhausted: please retry in 10.5 s") == 10.5
    assert gemini_worker.parse_retry_delay("{'error': {'details': [{'retryDelay': '25s'}]}}") == 25.0
    assert gemini_worker.parse_retry_delay('{"retryDelay": "25.09s"}') == 25.09
    assert gemini_worker.parse_retry_delay("retry_delay: 15.2") == 15.2
    assert gemini_worker.parse_retry_delay("random error with no delay") is None
    assert gemini_worker.parse_retry_delay(None) is None


def test_is_daily_quota():
    assert gemini_worker.is_daily_quota("Quota exceeded for quotaId: PerDayRequestsPerModel") is True
    assert gemini_worker.is_daily_quota("Error: quota_exceeded_daily reached") is True
    assert gemini_worker.is_daily_quota("429 RESOURCE_EXHAUSTED: Rate limit exceeded. Please retry in 25s.") is False
    assert gemini_worker.is_daily_quota(None) is False


def test_rate_limit_and_transient_classification():
    err = gemini_worker.GeminiRateLimitError("RESOURCE_EXHAUSTED: Rate limit exceeded after 6 attempts")
    logs = [str(err)]
    # is_transient_failure must classify RESOURCE_EXHAUSTED as transient for auto-retry
    assert is_transient_failure(logs) is True

    # But permanent markers must not be present
    permanent_err = [str(err), "clip detection failed"]
    assert is_transient_failure(permanent_err) is False


def test_gemini_ratelimiter(tmp_path):
    # Test slot acquisition under lock
    test_key = "test_api_key_12345"
    model = "test-model"
    ratelimit_dir = str(tmp_path / "ratelimit")

    # Acquire 2 slots with max_rpm=2
    t0 = time.time()
    w1 = gemini_ratelimit.acquire_gemini_slot(
        api_key=test_key,
        model_name=model,
        output_dir=ratelimit_dir,
        max_rpm=2
    )
    assert w1 == 0.0

    w2 = gemini_ratelimit.acquire_gemini_slot(
        api_key=test_key,
        model_name=model,
        output_dir=ratelimit_dir,
        max_rpm=2
    )
    assert w2 == 0.0

    # Ensure state file was written
    lock_dir = gemini_ratelimit._get_lock_dir(ratelimit_dir)
    assert os.path.isdir(lock_dir)
    files = os.listdir(lock_dir)
    assert any(f.endswith(".json") for f in files)


def test_whisper_cpu_threads(monkeypatch):
    monkeypatch.delenv("WHISPER_CPU_THREADS", raising=False)
    threads = transcribe_backends.get_whisper_cpu_threads()
    assert 4 <= threads <= 8

    monkeypatch.setenv("WHISPER_CPU_THREADS", "6")
    assert transcribe_backends.get_whisper_cpu_threads() == 6

    monkeypatch.setenv("WHISPER_CPU_THREADS", "12")
    assert transcribe_backends.get_whisper_cpu_threads() == 12


def test_resource_caps_defaults():
    assert MAX_CONCURRENT_JOBS == 1
    assert AUTO_RETRY_LIMIT == 1
    assert AUTO_RETRY_DELAY_SECONDS == 30.0


def test_status_endpoint_adaptive_polling(client, tmp_path):
    job_id = "f4c4a1b2-0000-0000-0000-000000000001"
    jobs[job_id] = {
        'status': 'processing',
        'logs': ['Line 1', 'Line 2', 'Line 3'],
        'stages': {
            'version': 5,
            'percent': 42.0,
            'mode': 'determinate',
            'stage_index': 2,
            'stage_total': 6
        }
    }

    try:
        # 1. Full request
        res1 = client.get(f"/api/status/{job_id}")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["version"] == 5
        assert len(data1["logs"]) == 3
        assert data1["log_offset"] == 3
        etag = res1.headers.get("etag")
        assert etag == '"5"'

        # 2. Since version unchanged + no new logs -> returns unchanged
        res2 = client.get(f"/api/status/{job_id}?since_version=5&log_offset=3")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2.get("unchanged") is True

        # 3. If-None-Match 304 Not Modified
        res3 = client.get(f"/api/status/{job_id}?log_offset=3", headers={"If-None-Match": '"5"'})
        assert res3.status_code == 304

        # 4. New logs arrived -> returns sliced logs
        jobs[job_id]['logs'].append('Line 4')
        res4 = client.get(f"/api/status/{job_id}?since_version=5&log_offset=3")
        assert res4.status_code == 200
        data4 = res4.json()
        assert data4.get("unchanged") is None
        assert data4["logs"] == ['Line 4']
        assert data4["log_offset"] == 4

    finally:
        jobs.pop(job_id, None)


def test_api_projects_disk_usage(client):
    res = client.get("/api/projects")
    assert res.status_code == 200
    data = res.json()
    assert "projects" in data
    assert "disk_usage" in data
    du = data["disk_usage"]
    assert "uploads_used_bytes" in du
    assert "uploads_cap_bytes" in du
    assert "output_used_bytes" in du
    assert "output_cap_bytes" in du
    assert "warning" in du
    assert isinstance(du["warning"], bool)
