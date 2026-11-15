import pytest
import os
import json
import shutil
import tempfile
from fastapi.testclient import TestClient
from app import app, jobs


@pytest.fixture
def client():
    return TestClient(app)


def test_api_projects_list_and_details(client):
    # Probar que /api/projects responde 200 con la lista de proyectos
    res = client.get("/api/projects")
    assert res.status_code == 200
    data = res.json()
    assert "projects" in data
    assert isinstance(data["projects"], list)


def test_api_projects_restore_and_delete(client, tmp_path):
    # Crear un proyecto falso en output/
    from app import OUTPUT_DIR, UPLOAD_DIR
    test_job_id = "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
    test_dir = os.path.join(OUTPUT_DIR, test_job_id)
    os.makedirs(test_dir, exist_ok=True)

    try:
        meta_content = {
            "title": "Proyecto API Test",
            "shorts": [
                {
                    "start": 0.0,
                    "end": 10.0,
                    "video_title_for_youtube_short": "Clip de prueba",
                    "predicted_score": 88
                }
            ]
        }
        meta_file = os.path.join(test_dir, "test_metadata.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta_content, f)

        clip_file = os.path.join(test_dir, "test_clip_1.mp4")
        with open(clip_file, "w") as f:
            f.write("dummy clip")

        # Comprobar listado
        res = client.get("/api/projects")
        assert res.status_code == 200
        proj_ids = [p["job_id"] for p in res.json()["projects"]]
        assert test_job_id in proj_ids

        # Comprobar detalle
        res_detail = client.get(f"/api/projects/{test_job_id}")
        assert res_detail.status_code == 200
        assert res_detail.json()["title"] == "Proyecto API Test"

        # Comprobar restore
        res_restore = client.post(f"/api/projects/{test_job_id}/restore")
        assert res_restore.status_code == 200
        restore_data = res_restore.json()
        assert restore_data["job_id"] == test_job_id
        assert restore_data["status"] == "completed"
        assert len(restore_data["result"]["clips"]) == 1

        # Comprobar delete
        res_del = client.delete(f"/api/projects/{test_job_id}")
        assert res_del.status_code == 200
        assert not os.path.exists(test_dir)

        # Comprobar que ya no aparece
        res_after = client.get(f"/api/projects/{test_job_id}")
        assert res_after.status_code == 404

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
