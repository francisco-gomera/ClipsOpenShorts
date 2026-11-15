import os
import json
import pytest
import shutil
import tempfile
from project_manager import (
    is_valid_job_id,
    canonical_clip_file,
    locate_source_file,
    determine_project_status,
    get_project_record,
    list_projects,
    recover_all_projects_to_memory,
    delete_project,
    clean_project_temp_files,
)


@pytest.fixture
def temp_env():
    """Crea directorios temporales de output y uploads para pruebas aisladas."""
    temp_dir = tempfile.mkdtemp()
    out_dir = os.path.join(temp_dir, "output")
    up_dir = os.path.join(temp_dir, "uploads")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(up_dir, exist_ok=True)
    yield out_dir, up_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_is_valid_job_id():
    assert is_valid_job_id("1a31f7c5-55af-44f2-86fc-5bc53c184694") is True
    assert is_valid_job_id("invalid-uuid") is False
    assert is_valid_job_id("thumbnails") is False


def test_canonical_clip_file_prefers_derived(temp_env):
    out_dir, _ = temp_env
    job_id = "11111111-2222-3333-4444-555555555555"
    job_path = os.path.join(out_dir, job_id)
    os.makedirs(job_path, exist_ok=True)

    base = "video1"
    clean = f"{base}_clip_1.mp4"
    clean_path = os.path.join(job_path, clean)
    with open(clean_path, "w") as f:
        f.write("clean")

    # Inicialmente devuelve la versión limpia
    assert canonical_clip_file(job_path, base, 0) == clean

    # Crear una versión subtitulada más reciente
    subtitled = f"subtitled_12345_{clean}"
    sub_path = os.path.join(job_path, subtitled)
    with open(sub_path, "w") as f:
        f.write("subtitled")

    assert canonical_clip_file(job_path, base, 0) == subtitled


def test_project_recovery_and_listing(temp_env):
    out_dir, up_dir = temp_env
    job_id = "22222222-3333-4444-5555-666666666666"
    job_path = os.path.join(out_dir, job_id)
    os.makedirs(job_path, exist_ok=True)

    # Crear metadata
    metadata = {
        "title": "Proyecto de Prueba",
        "duration": 60.0,
        "source_video": "source.mp4",
        "shorts": [
            {
                "start": 5.0,
                "end": 20.0,
                "video_title_for_youtube_short": "Clip 1",
                "predicted_score": 90,
            }
        ]
    }
    meta_path = os.path.join(job_path, "test_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f)

    # Crear clip real en disco
    clip_file = os.path.join(job_path, "test_clip_1.mp4")
    with open(clip_file, "w") as f:
        f.write("video data")

    # Crear archivo de origen en uploads
    src_file = os.path.join(up_dir, f"{job_id}_source.mp4")
    with open(src_file, "w") as f:
        f.write("source data")

    # Comprobar listado
    jobs_mem = {}
    projects = list_projects(out_dir, up_dir, jobs_mem)
    assert len(projects) == 1
    p = projects[0]
    assert p["job_id"] == job_id
    assert p["title"] == "Proyecto de Prueba"
    assert p["status"] == "completed"
    assert p["has_source"] is True
    assert p["clip_count"] == 1
    assert p["has_results"] is True

    # Comprobar recuperación en memoria
    recovered = recover_all_projects_to_memory(jobs_mem, out_dir, up_dir)
    assert recovered == 1
    assert job_id in jobs_mem
    assert jobs_mem[job_id]["status"] == "completed"
    assert len(jobs_mem[job_id]["result"]["clips"]) == 1


def test_delete_project(temp_env):
    out_dir, up_dir = temp_env
    job_id = "33333333-4444-5555-6666-777777777777"
    job_path = os.path.join(out_dir, job_id)
    os.makedirs(job_path, exist_ok=True)

    src_file = os.path.join(up_dir, f"{job_id}_video.mp4")
    with open(src_file, "w") as f:
        f.write("test")

    jobs_mem = {job_id: {"status": "completed"}}
    ok = delete_project(job_id, jobs_mem, out_dir, up_dir)
    assert ok is True
    assert not os.path.exists(job_path)
    assert not os.path.exists(src_file)
    assert job_id not in jobs_mem


def test_clean_project_temp_files(temp_env):
    out_dir, _ = temp_env
    job_id = "44444444-5555-6666-7777-888888888888"
    job_path = os.path.join(out_dir, job_id)
    os.makedirs(job_path, exist_ok=True)

    temp_file = os.path.join(job_path, "temp_preview.mp4")
    clean_file = os.path.join(job_path, "final_clip_1.mp4")
    with open(temp_file, "w") as f:
        f.write("temp")
    with open(clean_file, "w") as f:
        f.write("clean")

    # Modificar mtime del archivo temp a 3600s en el pasado
    old_time = os.path.getmtime(temp_file) - 4000
    os.utime(temp_file, (old_time, old_time))

    cleaned = clean_project_temp_files(job_id, out_dir, max_age_seconds=1800)
    assert cleaned == 1
    assert not os.path.exists(temp_file)
    assert os.path.exists(clean_file)
