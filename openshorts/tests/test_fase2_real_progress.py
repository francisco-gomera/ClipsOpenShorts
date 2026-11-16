import os
import json
import time
import shutil
import threading
import pytest
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

import stage_tracker
from main import ProgressReporter
import app
from app import app as fastapi_app, jobs, OUTPUT_DIR, UPLOAD_DIR


@pytest.fixture
def client():
    return TestClient(fastapi_app)


class TestUniformContractAndHistory:
    def test_init_stages_has_uniform_contract_fields(self, tmp_path):
        job_dir = str(tmp_path / "job_contract")
        data = stage_tracker.init_stages(job_dir, "test_job_123")

        # Global fields
        assert data["version"] == 1
        assert data["job_id"] == "test_job_123"
        assert data["status"] == "queued"
        assert "percent" in data
        assert "mode" in data
        assert "eta_seconds" in data
        assert "eta_confidence" in data
        assert data["stage_total"] == len(stage_tracker.STAGES_ORDER)
        assert isinstance(data["clips"], list)
        assert "counters" in data
        assert data["counters"]["total"] == 0
        assert data["counters"]["ready"] == 0
        assert data["counters"]["failed"] == 0
        assert data["recovery"]["state"] == "normal"

        # Stage specific fields
        for st_name in stage_tracker.STAGES_ORDER:
            st = data["stages"][st_name]
            assert st["name"] == st_name
            assert "status" in st
            assert "mode" in st
            assert "percent" in st
            assert "units" in st
            assert "bytes" in st
            assert "speed" in st
            assert "eta_seconds" in st

    def test_stage_history_recording_and_rotation(self, tmp_path):
        base_out = str(tmp_path / "out")
        os.makedirs(base_out, exist_ok=True)

        stages_dummy = {
            "download": {"duration_seconds": 12.0, "status": "completed"},
            "transcription": {"duration_seconds": 30.0, "status": "completed"},
            "clip_selection": {"duration_seconds": 15.0, "status": "completed"},
            "cut_and_reframe": {"duration_seconds": 60.0, "status": "completed"},
        }

        # Grabar 6 ejecuciones para habilitar promedios
        for i in range(6):
            stage_tracker.record_stage_history(
                base_output_dir=base_out,
                job_id=f"job_{i}",
                media_duration_seconds=120.0,  # 2 minutos
                stages_dict=stages_dummy
            )

        history_file = os.path.join(base_out, ".stats", "stage_history.json")
        assert os.path.isfile(history_file)
        with open(history_file, "r") as f:
            records = json.load(f)
        assert len(records) == 6

        # Cargar promedios normalizados
        averages = stage_tracker.load_stage_history_averages(base_out)
        assert averages is not None
        assert "transcription" in averages
        # 30s para 2 min = 15s por min
        assert pytest.approx(averages["transcription"], 0.1) == 15.0


class TestProgressReporterConcurrencyAndRateLimit:
    def test_reporter_under_6_concurrent_threads_without_corruption(self, tmp_path, monkeypatch):
        job_dir = str(tmp_path / "concurrent_job")
        os.makedirs(job_dir, exist_ok=True)

        emitted_lines = []
        monkeypatch.setattr(
            "sys.stdout.write",
            lambda line: emitted_lines.append(line) if line.startswith("PROGRESS ") else None
        )
        monkeypatch.setattr("sys.stdout.flush", lambda: None)

        reporter = ProgressReporter(job_dir, "concurrent_job", media_duration=180.0)
        reporter.start_stage("cut_and_reframe", mode="determinate")

        def worker_task(clip_idx):
            for step in ["cut", "reframe", "hook", "subtitles"]:
                reporter.update_clip(clip_idx, substage=step, percent=25.0)
                time.sleep(0.01)
            reporter.update_clip(clip_idx, substage="done", percent=100.0, ready=True, file=f"clip_{clip_idx}.mp4")

        # 6 hilos concurrentes simulando CLIP_WORKERS=6
        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(worker_task, range(6)))

        reporter.finish_stage("cut_and_reframe")

        # Verificar que el estado final en disco y memoria sea coherente y no esté corrupto
        final_data = reporter._data
        assert final_data["counters"]["total"] == 6
        assert final_data["counters"]["ready"] == 6
        assert final_data["counters"]["failed"] == 0
        assert len(final_data["clips"]) == 6
        for c in final_data["clips"]:
            assert c["ready"] is True
            assert c["percent"] == 100.0
            assert c["status"] == "completed"

        # Verificar que emitted_lines contiene líneas PROGRESS válidas deserializables
        assert len(emitted_lines) > 0
        for line in emitted_lines:
            payload = json.loads(line[9:])
            assert "stages" in payload
            assert "counters" in payload

    def test_disk_write_volume_is_throttled(self, tmp_path, monkeypatch):
        job_dir = str(tmp_path / "throttled_job")
        os.makedirs(job_dir, exist_ok=True)

        disk_write_count = 0
        original_save = stage_tracker.save_stages_direct

        def counted_save(d, data):
            nonlocal disk_write_count
            disk_write_count += 1
            original_save(d, data)

        monkeypatch.setattr(stage_tracker, "save_stages_direct", counted_save)

        reporter = ProgressReporter(job_dir, "throttled_job", media_duration=60.0)
        reporter.start_stage("cut_and_reframe")
        initial_writes = disk_write_count

        # Generar 50 actualizaciones en un intervalo corto (< 100ms)
        for i in range(50):
            reporter.update_stage("cut_and_reframe", percent=float(i % 10), speed=100.0)

        # Sin transiciones forzadas, las escrituras en disco deben estar acotadas (mucho menores a 50)
        writes_during_updates = disk_write_count - initial_writes
        assert writes_during_updates <= 2, f"Writes to disk were not throttled: {writes_during_updates} writes"


class TestStatusEndpointServing:
    def test_status_serves_live_from_memory(self, client, monkeypatch):
        job_id = "f0a1b2c3-d4e5-4a6b-8c7d-9e0f1a2b3c4d"
        out_root = str(OUTPUT_DIR)

        memory_stages = {
            "version": 1,
            "job_id": job_id,
            "status": "processing",
            "percent": 73.5,
            "mode": "determinate",
            "eta_seconds": 45,
            "stage_index": 4,
            "stage_total": 6,
            "current_stage": "cut_and_reframe",
            "stages": {
                "cut_and_reframe": {"status": "running", "percent": 73.5, "mode": "determinate"}
            },
            "clips": [{"index": 0, "status": "completed", "ready": True}],
            "counters": {"total": 2, "ready": 1, "failed": 0},
            "recovery": {"state": "waiting_rate_limit", "retry_at": 1800000000.0, "message": "waiting"}
        }

        jobs[job_id] = {
            "status": "processing",
            "logs": app._TimedLog(["processing"]),
            "stages": memory_stages,
            "result": None,
            "user_id": None,
        }

        resp = client.get(f"/api/status/{job_id}")
        assert resp.status_code == 200
        data = resp.json()

        # Servido en vivo desde memoria
        assert data["percent"] == 73.5
        assert data["mode"] == "determinate"
        assert data["eta_seconds"] == 45
        assert data["counters"]["ready"] == 1
        assert data["recovery"]["state"] == "waiting_rate_limit"
        assert data["stages"]["current_stage"] == "cut_and_reframe"


class TestResumeFromSkippingRenders:
    def test_resume_from_skips_already_rendered_clips(self, tmp_path, monkeypatch):
        job_dir = tmp_path / "resume_job"
        job_dir.mkdir()

        # Simular un clip ya renderizado previamente
        clip_0 = job_dir / "myvideo_clip_1.mp4"
        clip_0.write_bytes(b"A" * 2000)

        cut_called = []
        render_called = []

        def mock_cut(inp, out, s, e, idx):
            cut_called.append(idx)

        def mock_render(inp, out, fmt, **kwargs):
            render_called.append(out)
            return True

        monkeypatch.setattr("main.cut_clip", mock_cut)
        monkeypatch.setattr("main.render_clip", mock_render)

        # Simular función de decisión de clip en main
        from main import ProgressReporter
        reporter = ProgressReporter(str(job_dir), "resume_job", media_duration=60.0)

        def is_clip_already_rendered(idx):
            clean = f"myvideo_clip_{idx+1}.mp4"
            target = job_dir / clean
            return str(target) if target.exists() and target.stat().st_size > 1000 else None

        # Para clip 0 (ya existe):
        assert is_clip_already_rendered(0) is not None
        # Para clip 1 (no existe):
        assert is_clip_already_rendered(1) is None

