import json
import sys

import pytest

from live.blocks import (BlockManager, block_pipeline_command, build_block_timeline,
                         clip_overlaps_prior, map_mp4_range)
from live.child_env import CHILD_ENV_DENYLIST, child_env


def test_block_manifest_is_atomic_and_interrupted_work_is_requeued(tmp_path):
    manager = BlockManager(tmp_path)
    block = manager.open_block(0, 0, 2400)
    manager.set_phase(block["id"], "renderizando")

    recovered = BlockManager(tmp_path)
    assert recovered.get(block["id"])["phase"] == "en_cola"
    assert json.loads((tmp_path / "blocks.json").read_text())["blocks"][0]["attempts"] == 1


def test_map_mp4_range_respects_timeline_gaps_and_rejects_crossing(tmp_path):
    del tmp_path
    timeline = [
        {"mp4_start_s": 0, "session_start_s": 0, "duration_s": 100},
        {"mp4_start_s": 100, "session_start_s": 140, "duration_s": 100},
    ]
    assert map_mp4_range(timeline, 120, 130) == {"start_s": 160, "end_s": 170}
    assert map_mp4_range(timeline, 95, 100) == {"start_s": 95, "end_s": 100}
    with pytest.raises(ValueError, match="cruza_hueco"):
        map_mp4_range(timeline, 95, 105)


def test_timeline_converts_first_and_overlapped_blocks_without_double_subtraction():
    first = [{"mp4_start_s": 0, "session_start_s": 0, "duration_s": 2400}]
    second = [{"mp4_start_s": 0, "session_start_s": 2310, "duration_s": 2400}]
    assert map_mp4_range(first, 750, 780)["start_s"] == 750
    assert map_mp4_range(second, 750, 780)["start_s"] == 3060


def test_timeline_applies_reconnection_gap_after_cut_and_accepts_subsecond_seams():
    timeline = [
        {"mp4_start_s": 0, "session_start_s": 0, "duration_s": 100},
        {"mp4_start_s": 100, "session_start_s": 140, "duration_s": 200},
    ]
    assert map_mp4_range(timeline, 150, 160)["start_s"] == 190
    tiny_gap = [
        {"mp4_start_s": 0, "session_start_s": 0, "duration_s": 100},
        {"mp4_start_s": 100, "session_start_s": 100.5, "duration_s": 200},
    ]
    assert map_mp4_range(tiny_gap, 99.5, 100.5)["end_s"] == 101.0


def test_segment_ownership_keeps_overlapping_segment_until_both_blocks_finish(tmp_path):
    segments = tmp_path / "segments"
    segments.mkdir()
    shared = segments / "seg_000001.ts"
    shared.write_bytes(b"transport stream")
    manager = BlockManager(tmp_path)
    first = manager.open_block(0, 0, 2400)
    second = manager.open_block(1, 2400, 4800)
    for block in (first, second):
        manager.set_phase(block["id"], "completado")
        manager.register_segment(block["id"], shared.name)
    manager.save()

    manager.release_segments(first["id"])
    assert shared.exists()
    manager.release_segments(second["id"])
    assert not shared.exists()


def test_block_pipeline_child_environment_drops_server_secrets():
    env = child_env({"GEMINI_API_KEY": "pipeline-key", "JWT_SECRET": "server-key",
                     "DATABASE_URL": "private-db", "PATH": "/usr/bin"})
    assert env["GEMINI_API_KEY"] == "pipeline-key"
    assert env["PATH"] == "/usr/bin"
    assert all(name not in env for name in CHILD_ENV_DENYLIST)


def test_pipeline_command_override_is_available_only_to_pytest_workers():
    args = {"LIVE_BLOCK_PIPELINE_CMD": "python fake_pipeline.py", "PYTEST_CURRENT_TEST": "test"}
    assert block_pipeline_command("main.py", "block.mp4", "out", env=args) == [
        "python", "fake_pipeline.py", "-i", "block.mp4", "-o", "out", "--generation-mode", "smart"]
    assert block_pipeline_command("main.py", "block.mp4", "out",
                                  env={"LIVE_BLOCK_PIPELINE_CMD": "python bad.py"})[0] == sys.executable


def test_block_timeline_keeps_session_boundary_and_reports_missing_media_time():
    timeline, gaps = build_block_timeline([
        {"index": 0, "name": "seg_000000.ts", "session_start_s": 0, "duration_s": 10},
        {"index": 1, "name": "seg_000001.ts", "session_start_s": 10, "duration_s": 10},
        {"index": 2, "name": "seg_000002.ts", "session_start_s": 60, "duration_s": 10},
    ], 0, 70)
    assert [item["mp4_start_s"] for item in timeline] == [0, 20]
    assert sum(item["duration_s"] for item in timeline) == 30
    assert gaps == [{"at_session_s": 20, "seconds": 40}]


def test_deduplication_uses_absolute_session_ranges():
    previous = [{"start": 700, "end": 740}]
    assert clip_overlaps_prior(725, 765, previous)
    assert not clip_overlaps_prior(741, 780, previous)


def test_manifest_updates_from_worker_and_retry_endpoint_merge_without_lost_fields(tmp_path):
    seed = BlockManager(tmp_path)
    block = seed.open_block(0, 0, 2400)
    seed.set_phase(block["id"], "error", error="fallo")
    worker = BlockManager(tmp_path, recover=False)
    api = BlockManager(tmp_path, recover=False)

    api.retry(block["id"])
    worker.register_segment(block["id"], "seg_000001.ts")

    current = BlockManager(tmp_path, recover=False).get(block["id"])
    assert current["phase"] == "en_cola"
    assert current["segments"] == ["seg_000001.ts"]


def test_open_pending_and_error_owners_cannot_release_segments(tmp_path):
    segments = tmp_path / "segments"
    segments.mkdir()
    path = segments / "seg_000001.ts"
    path.write_bytes(b"keep")
    manager = BlockManager(tmp_path)
    block = manager.open_block(0, 0, 2400)
    manager.register_segment(block["id"], path.name)

    assert manager.release_segments(block["id"]) == []
    manager.set_phase(block["id"], "error")
    assert manager.release_segments(block["id"]) == []
    assert path.exists()
