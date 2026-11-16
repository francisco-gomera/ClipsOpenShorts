import os
import json
import uuid
import shutil
import pytest
from fastapi.testclient import TestClient

from app import app, jobs, OUTPUT_DIR, UPLOAD_DIR
from project_manager import is_valid_job_id, validate_job_id, delete_project
import stage_tracker


@pytest.fixture
def client():
    return TestClient(app)


class TestIdentifierValidationAndTraversal:
    def test_is_valid_job_id_with_valid_uuids(self):
        valid_uuid = str(uuid.uuid4())
        assert is_valid_job_id(valid_uuid) is True
        assert is_valid_job_id("f147e00f-a03a-4c09-8586-1f4521c246c0") is True

    def test_is_valid_job_id_rejects_malicious_inputs(self):
        malicious = [
            "..",
            "../..",
            "%2e%2e",
            "/etc/passwd",
            "C:\\Windows\\System32",
            "12345",
            "not-a-uuid",
            "",
            None,
            "f147e00f-a03a-4c09-8586-1f4521c246c0/extra",
            "f147e00f-a03a-4c09-8586-1f4521c246c0\x00poison",
        ]
        for item in malicious:
            assert is_valid_job_id(item) is False

    def test_validate_job_id_raises_value_error_on_traversal(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        with pytest.raises(ValueError):
            validate_job_id("..", base_dir)

        with pytest.raises(ValueError):
            validate_job_id("../secret", base_dir)

        with pytest.raises(ValueError):
            validate_job_id("invalid-uuid", base_dir)

        valid_uuid = str(uuid.uuid4())
        assert validate_job_id(valid_uuid, base_dir) == valid_uuid

    def test_delete_project_refuses_traversal_and_does_not_delete_parent(self, tmp_path):
        parent_dir = tmp_path / "sandbox"
        parent_dir.mkdir()
        out_dir = str(parent_dir / "output")
        up_dir = str(parent_dir / "uploads")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(up_dir, exist_ok=True)

        canary_file = parent_dir / "canary.txt"
        canary_file.write_text("must survive", encoding="utf-8")

        mock_jobs = {}
        with pytest.raises(ValueError):
            delete_project("..", mock_jobs, out_dir, up_dir)

        assert canary_file.exists()
        assert canary_file.read_text(encoding="utf-8") == "must survive"
        assert os.path.isdir(out_dir)

    def test_api_endpoints_reject_malicious_job_id(self, client):
        bad_endpoints = [
            ("GET", "/api/projects/.."),
            ("GET", "/api/projects/invalid-id"),
            ("DELETE", "/api/projects/.."),
            ("DELETE", "/api/projects/invalid-id"),
            ("POST", "/api/jobs/../retry"),
            ("POST", "/api/jobs/invalid-id/retry"),
            ("GET", "/api/status/.."),
            ("GET", "/api/status/invalid-id"),
        ]
        for method, endpoint in bad_endpoints:
            resp = client.request(method, endpoint)
            assert resp.status_code in (400, 404), f"Failed for {method} {endpoint}: got {resp.status_code}"


class TestRetryEndpointStabilization:
    def test_retry_creates_job_with_env_key(self, client, tmp_path):
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        try:
            # Create stages.json in failed state
            stage_tracker.init_stages(job_dir, job_id)
            stage_tracker.finish_stage(job_dir, "clip_selection", error="Simulated 429 quota")

            # Create dummy checkpoint transcript so can_retry is True
            with open(os.path.join(job_dir, ".transcript_checkpoint.json"), "w") as f:
                json.dump({"transcript": {"segments": [{"start": 0, "end": 5, "text": "hello"}]}}, f)

            resp = client.post(
                f"/api/jobs/{job_id}/retry",
                headers={"X-Gemini-Key": "test_byok_gemini_key_123"}
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["success"] is True
            assert data["status"] == "queued"

            # Check that jobs[job_id] contains 'env'
            assert job_id in jobs
            assert "env" in jobs[job_id]
            assert isinstance(jobs[job_id]["env"], dict)
            assert jobs[job_id]["env"].get("GEMINI_API_KEY") == "test_byok_gemini_key_123"

        finally:
            jobs.pop(job_id, None)
            shutil.rmtree(job_dir, ignore_errors=True)

    def test_retry_rejects_completed_job_without_force(self, client, tmp_path):
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        try:
            stage_tracker.init_stages(job_dir, job_id)
            stage_tracker.complete_job(job_dir)
            with open(os.path.join(job_dir, ".transcript_checkpoint.json"), "w") as f:
                json.dump({"transcript": {"segments": [{"start": 0, "end": 5, "text": "hello"}]}}, f)

            jobs[job_id] = {"status": "completed"}

            # Normal retry should receive 409 Conflict
            resp = client.post(f"/api/jobs/{job_id}/retry")
            assert resp.status_code == 409

            # Retry with force=true should be accepted
            resp_force = client.post(f"/api/jobs/{job_id}/retry?force=true")
            assert resp_force.status_code == 200

        finally:
            jobs.pop(job_id, None)
            shutil.rmtree(job_dir, ignore_errors=True)

    def test_build_retry_command_restores_job_options(self, tmp_path):
        job_id = str(uuid.uuid4())
        job_dir = str(tmp_path / "output" / job_id)
        upload_dir = str(tmp_path / "uploads")
        os.makedirs(job_dir, exist_ok=True)
        os.makedirs(upload_dir, exist_ok=True)

        # Save non-secret job options
        opts = {
            "format": "vertical",
            "keep_original": True,
            "skip_analysis": False
        }
        with open(os.path.join(job_dir, "job_options.json"), "w") as f:
            json.dump(opts, f)

        # Create dummy source in uploads
        src = os.path.join(upload_dir, f"{job_id}_video.mp4")
        with open(src, "w") as f:
            f.write("mock")

        cmd = stage_tracker.build_retry_command(job_id, str(tmp_path / "output"), upload_dir)
        assert "--format" in cmd
        assert cmd[cmd.index("--format") + 1] == "vertical"
        assert "--keep-original" in cmd


class TestStageFailureMarking:
    def test_mark_stage_failed_records_stage_and_job_failure(self, tmp_path):
        job_dir = str(tmp_path / "test_job")
        os.makedirs(job_dir, exist_ok=True)

        stage_tracker.init_stages(job_dir, "test_job")
        stage_tracker.start_stage(job_dir, "transcription")

        # Mark failure
        data = stage_tracker.mark_stage_failed(job_dir, error="Out of memory in ASR")
        assert data["status"] == "failed"
        assert data["stages"]["transcription"]["status"] == "failed"
        assert data["stages"]["transcription"]["error"] == "Out of memory in ASR"

        # Verify disk persistence
        disk_data = stage_tracker.read_stages(job_dir)
        assert disk_data["status"] == "failed"
        assert disk_data["stages"]["transcription"]["status"] == "failed"


class TestHookPreservationAndSubtitleBand:
    def test_hook_size_recorded_in_auto_hook(self, client, monkeypatch):
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        def mock_add_hook(video_path, text, output_path, *args, **kwargs):
            with open(output_path, "w") as f:
                f.write("mocked hooked video")
            return {"y": 384}

        monkeypatch.setattr("app.add_hook_to_video", mock_add_hook)

        try:
            # Create dummy clip & metadata
            meta = {
                "shorts": [
                    {
                        "start": 0.0,
                        "end": 10.0,
                        "video_title_for_youtube_short": "Clip 1",
                        "auto_hook": None
                    }
                ]
            }
            meta_path = os.path.join(job_dir, "video_metadata.json")
            with open(meta_path, "w") as f:
                json.dump(meta, f)

            # Create dummy clip video file
            clip_file = os.path.join(job_dir, "video_clip_1.mp4")
            with open(clip_file, "w") as f:
                f.write("dummy video")

            jobs[job_id] = {
                "status": "completed",
                "result": {"clips": [{"video_url": f"/videos/{job_id}/video_clip_1.mp4"}]}
            }

            # Apply hook with size "L"
            resp = client.post("/api/hook", json={
                "job_id": job_id,
                "clip_index": 0,
                "text": "INCREDIBLE HOOK",
                "size": "L",
                "position": "top",
                "style": "classic",
                "duration_seconds": 5.0
            })
            assert resp.status_code == 200, resp.text
            res_data = resp.json()
            assert res_data["success"] is True
            assert res_data["burned_hook"]["size"] == "L"

            # Check that size survives in metadata
            with open(meta_path, "r") as f:
                updated_meta = json.load(f)
            assert updated_meta["shorts"][0]["auto_hook"]["size"] == "L"

        finally:
            jobs.pop(job_id, None)
            shutil.rmtree(job_dir, ignore_errors=True)
