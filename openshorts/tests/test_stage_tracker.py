import os
import json
import pytest
import stage_tracker


def test_init_and_read_stages(tmp_path):
    job_dir = str(tmp_path / "test_job")
    data = stage_tracker.init_stages(job_dir, "test_job")
    assert data["job_id"] == "test_job"
    assert data["status"] == "queued"
    assert "stages" in data
    assert "download" in data["stages"]
    assert data["stages"]["download"]["status"] == "pending"

    read_data = stage_tracker.read_stages(job_dir)
    assert read_data is not None
    assert read_data["job_id"] == "test_job"


def test_stage_lifecycle(tmp_path):
    job_dir = str(tmp_path / "test_job")
    stage_tracker.init_stages(job_dir, "test_job")

    # Start download
    s1 = stage_tracker.start_stage(job_dir, "download")
    assert s1["stages"]["download"]["status"] == "running"
    assert s1["stages"]["download"]["started_at"] is not None

    # Finish download
    s2 = stage_tracker.finish_stage(job_dir, "download")
    assert s2["stages"]["download"]["status"] == "completed"
    assert s2["stages"]["download"]["completed_at"] is not None
    assert s2["stages"]["download"]["duration_seconds"] is not None

    # Fail a stage
    s3 = stage_tracker.finish_stage(job_dir, "transcription", error="API rate limit")
    assert s3["status"] == "failed"
    assert s3["stages"]["transcription"]["status"] == "failed"
    assert s3["stages"]["transcription"]["error"] == "API rate limit"


def test_infer_stages_from_disk(tmp_path):
    job_dir = tmp_path / "interrupted_job"
    job_dir.mkdir()

    # Escribir checkpoint de transcripción y metadata simulando fallo en renderizado
    meta = {
        "shorts": [{"index": 0, "start": 10, "end": 30}],
        "transcript": {"segments": [{"start": 0, "end": 30, "text": "hello"}]},
    }
    (job_dir / "test_metadata.json").write_text(json.dumps(meta))
    (job_dir / ".transcript_checkpoint.json").write_text(json.dumps({"transcript": meta["transcript"]}))

    inferred = stage_tracker.infer_stages_from_disk(str(job_dir), "interrupted_job")
    assert inferred["stages"]["transcription"]["status"] == "completed"
    assert inferred["stages"]["clip_selection"]["status"] == "completed"
    # Sin clips renderizados, cut_and_reframe queda pending
    assert inferred["stages"]["cut_and_reframe"]["status"] == "pending"
    assert inferred["status"] == "interrupted"


def test_build_retry_command(tmp_path):
    job_dir = tmp_path / "output" / "retry_job"
    job_dir.mkdir(parents=True)
    up_dir = tmp_path / "uploads"
    up_dir.mkdir(parents=True)

    # Simular source video en uploads
    src_file = up_dir / "retry_job_video.mp4"
    src_file.write_bytes(b"video content")

    # Simular transcript checkpoint
    t_file = job_dir / ".transcript_checkpoint.json"
    t_file.write_text(json.dumps({
        "transcript": {"segments": [{"start": 0, "end": 10, "text": "test"}]}
    }))

    cmd = stage_tracker.build_retry_command("retry_job", str(tmp_path / "output"), str(up_dir))
    assert "-i" in cmd
    assert str(src_file) in cmd
    assert "--transcript" in cmd
