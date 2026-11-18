import os
import time
import subprocess
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app import app, jobs, _active_processes, _clean_job_temp_artifacts
import stage_tracker
from main import raise_if_cancelled, check_job_cancelled, JobCancelledException


@pytest.fixture
def client():
    return TestClient(app)


def test_cancel_endpoint_inactive_job(client):
    """Cancelar un job que no está activo devuelve 400."""
    res = client.post("/api/jobs/00000000-0000-0000-0000-000000000001/cancel")
    assert res.status_code == 400


def test_cancel_endpoint_active_job_and_idempotency(client, tmp_path):
    """Cancelar un job activo lo marca como cancelled, escribe .cancel y es idempotente."""
    job_id = "11111111-1111-1111-1111-111111111111"
    job_dir = str(tmp_path / job_id)
    os.makedirs(job_dir, exist_ok=True)

    # Registrar el job como activo
    jobs[job_id] = {
        "status": "processing",
        "output_dir": job_dir,
        "logs": [],
        "cmd": ["python", "-c", "import time; time.sleep(10)"],
    }
    stage_tracker.init_stages(job_dir, job_id)
    stage_tracker.start_stage(job_dir, "transcription")

    with patch("app.OUTPUT_DIR", str(tmp_path)):
        # 1. Primera solicitud de cancelación
        res1 = client.post(f"/api/jobs/{job_id}/cancel")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["success"] is True
        assert data1["status"] == "cancelled"
        assert jobs[job_id]["status"] == "cancelled"
        assert os.path.exists(os.path.join(job_dir, ".cancel"))

        stages = stage_tracker.read_stages(job_dir)
        assert stages["status"] == "cancelled"

        # 2. Segunda solicitud (idempotencia)
        res2 = client.post(f"/api/jobs/{job_id}/cancel")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is True
        assert data2["status"] == "cancelled"


def test_clean_job_temp_artifacts_preserves_original_video(tmp_path):
    """La limpieza de temporales borra archivos temporales y fragmentos pero preserva el video original."""
    job_dir = str(tmp_path / "job_clean_test")
    os.makedirs(job_dir, exist_ok=True)

    # Archivo original que DEBE preservarse
    orig_video = os.path.join(job_dir, "source_video.mp4")
    with open(orig_video, "w") as f:
        f.write("original video content")

    # Archivos temporales que DEBEN eliminarse
    temp_files = [
        "temp_clip_1.mp4",
        "hooked_1_clip_1.mp4",
        "subtitled_1_clip_1.mp4",
        "autosubs_1.ass",
        "wm_clip_1.mp4",
        "myvideo_clip_1.mp4",
        "myvideo_metadata.json",
        ".transcript_checkpoint.json",
        ".score_checkpoint.json",
    ]
    for tf in temp_files:
        with open(os.path.join(job_dir, tf), "w") as f:
            f.write("temporary file")

    _clean_job_temp_artifacts(job_dir)

    # Verificar que el original sigue intacto
    assert os.path.exists(orig_video), "El video original no debe eliminarse"
    with open(orig_video, "r") as f:
        assert f.read() == "original video content"

    # Verificar que los temporales fueron borrados
    for tf in temp_files:
        assert not os.path.exists(os.path.join(job_dir, tf)), f"{tf} debería haber sido eliminado"


def test_main_pipeline_cancellation_detection(tmp_path):
    """main.py detecta el archivo .cancel y lanza JobCancelledException en etapas y loops paralelos."""
    job_dir = str(tmp_path / "pipeline_test")
    os.makedirs(job_dir, exist_ok=True)

    # Inicialmente no cancelado
    assert check_job_cancelled(job_dir) is False
    raise_if_cancelled(job_dir)  # no debe lanzar

    # Crear .cancel
    with open(os.path.join(job_dir, ".cancel"), "w") as f:
        f.write("cancelled")

    assert check_job_cancelled(job_dir) is True
    with pytest.raises(JobCancelledException):
        raise_if_cancelled(job_dir)
