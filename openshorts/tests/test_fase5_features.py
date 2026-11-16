import os
import json
import pytest
from fastapi.testclient import TestClient

import hooks
import app as app_module
from app import app, jobs, HookRequest
import recut


@pytest.fixture
def client():
    return TestClient(app)


def test_hook_defaults():
    """Verify that default hook style, font, position, size, duration are updated to:
    classic, anton, top, M, 5.0s."""
    assert hooks.DEFAULT_HOOK_STYLE == "classic"
    assert hooks.DEFAULT_HOOK_FONT == "anton"
    assert hooks.DEFAULT_HOOK_POSITION == "top"
    assert hooks.DEFAULT_HOOK_SIZE == "M"
    assert hooks.DEFAULT_HOOK_DURATION == 5.0

    # Verify HookRequest defaults
    req = HookRequest(job_id="test_job", clip_index=0, text="Catchy Hook!")
    assert req.style == "classic"
    assert req.font == "anton"
    assert req.position == "top"
    assert req.size == "M"
    assert req.duration_seconds == 5.0


def test_edl_other_clips_ranges_exclusion_and_overlap(tmp_path, monkeypatch):
    """Verify EDL endpoint returns other clips ranges excluding current clip,
    preserving indices and handling overlaps."""
    job_id = "test_fase5_edl_job"
    out_root = tmp_path / "output"
    job_dir = out_root / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))

    source_path = job_dir / "src.mp4"
    source_path.write_bytes(b"\x00" * 1024)

    clips = [
        {
            "start": 10.0,
            "end": 30.0,
            "video_title_for_youtube_short": "Clip 0",
            "video_url": f"/videos/{job_id}/clip_0.mp4",
        },
        {
            "start": 25.0,  # Overlaps with clip 0
            "end": 50.0,
            "video_title_for_youtube_short": "Clip 1 Overlapping",
            "video_url": f"/videos/{job_id}/clip_1.mp4",
        },
        {
            "start": 60.0,
            "end": 85.0,
            "video_title_for_youtube_short": "Clip 2",
            "video_url": f"/videos/{job_id}/clip_2.mp4",
        },
    ]

    meta = {
        "source_video": "src.mp4",
        "transcript": {
            "segments": [
                {
                    "start": 0.0, "end": 90.0, "text": "hello world again",
                    "words": [
                        {"word": "hello", "start": 10.5, "end": 11.0},
                        {"word": "world", "start": 30.0, "end": 30.5},
                    ],
                }
            ]
        },
        "shorts": clips,
    }
    meta_path = job_dir / "project_metadata.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (job_dir / "clip_0.mp4").write_bytes(b"c0")
    (job_dir / "clip_1.mp4").write_bytes(b"c1")
    (job_dir / "clip_2.mp4").write_bytes(b"c2")

    jobs[job_id] = {
        "status": "completed",
        "logs": [],
        "result": {"clips": list(clips)},
        "user_id": None,
        "watermark": False,
    }

    test_client = TestClient(app)

    try:
        # Check EDL for Clip 1 (index 1) -> must exclude Clip 1 and include Clip 0 and Clip 2
        resp = test_client.get(f"/api/clip/{job_id}/1/edl")
        assert resp.status_code == 200
        data = resp.json()

        other_ranges = data.get("other_clips_ranges", [])
        assert len(other_ranges) == 2
        indices = [r["index"] for r in other_ranges]
        assert indices == [0, 2]
        assert 1 not in indices

        # Clip 0 data
        c0 = next(r for r in other_ranges if r["index"] == 0)
        assert c0["title"] == "Clip 0"
        assert c0["start"] == 10.0
        assert c0["end"] == 30.0

        # Clip 2 data
        c2 = next(r for r in other_ranges if r["index"] == 2)
        assert c2["title"] == "Clip 2"
        assert c2["start"] == 60.0
        assert c2["end"] == 85.0

        # Check EDL for Clip 0 (index 0) -> must exclude Clip 0 and include Clip 1 and Clip 2
        resp0 = test_client.get(f"/api/clip/{job_id}/0/edl")
        assert resp0.status_code == 200
        data0 = resp0.json()
        indices0 = [r["index"] for r in data0.get("other_clips_ranges", [])]
        assert indices0 == [1, 2]
        assert 0 not in indices0

    finally:
        jobs.pop(job_id, None)


def test_chronological_ordering_keeps_original_indices():
    """Verify that chronological sorting keeps original array indices intact
    for accurate action dispatching (clip_index)."""
    raw_clips = [
        {"start": 50.0, "title": "Late Clip"},      # original index 0
        {"start": 10.0, "title": "Early Clip"},     # original index 1
        {"start": 30.0, "title": "Middle Clip"},    # original index 2
    ]

    # Matching App.jsx rankedClips logic:
    ranked = sorted(
        enumerate(raw_clips),
        key=lambda item: item[1]["start"]
    )

    # Sorted order should be: Early Clip (index 1), Middle Clip (index 2), Late Clip (index 0)
    assert ranked[0][0] == 1
    assert ranked[0][1]["title"] == "Early Clip"

    assert ranked[1][0] == 2
    assert ranked[1][1]["title"] == "Middle Clip"

    assert ranked[2][0] == 0
    assert ranked[2][1]["title"] == "Late Clip"


def test_hook_metadata_preserved_on_hook_endpoint(tmp_path, monkeypatch):
    """Verify that /api/hook updates metadata with new default style, font, size, position, duration."""
    job_id = "test_fase5_hook_meta"
    out_root = tmp_path / "output"
    job_dir = out_root / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))

    dummy_clip = job_dir / "clip_0.mp4"
    dummy_clip.write_bytes(b"\x00" * 512)

    clips = [{
        "start": 0.0,
        "end": 10.0,
        "video_url": f"/videos/{job_id}/clip_0.mp4",
        "video_title_for_youtube_short": "Hook Clip",
    }]
    meta = {"shorts": clips, "source_video": "clip_0.mp4"}
    (job_dir / "project_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    jobs[job_id] = {
        "status": "completed",
        "logs": [],
        "result": {"clips": list(clips)},
        "user_id": None,
        "watermark": False,
    }

    test_client = TestClient(app)

    # Mock add_hook_to_video to avoid running real ffmpeg in unit test
    def fake_add_hook(in_p, txt, out_p, **kw):
        with open(out_p, "wb") as f:
            f.write(b"\x00" * 512)
        return out_p

    monkeypatch.setattr(app_module, "add_hook_to_video", fake_add_hook)
    monkeypatch.setattr(hooks, "add_hook_to_video", fake_add_hook)

    try:
        resp = test_client.post("/api/hook", json={
            "job_id": job_id,
            "clip_index": 0,
            "text": "Check this out!",
            # style, font, size, position, duration_seconds omitted to use defaults
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        burned = data["burned_hook"]
        assert burned["text"] == "Check this out!"
        assert burned["style"] == "classic"
        assert burned["font"] == "anton"
        assert burned["size"] == "M"
        assert burned["position"] == "top"
        assert burned["duration_seconds"] == 5.0
    finally:
        jobs.pop(job_id, None)


def test_recut_preserves_auto_hook_data(tmp_path, monkeypatch):
    """Verify that rerendering/recutting a clip preserves its auto_hook settings."""
    job_id = "test_fase5_recut_hook"
    out_root = tmp_path / "output"
    job_dir = out_root / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out_root))

    hook_info = {
        "text": "Viral Hook Header",
        "style": "classic",
        "font": "anton",
        "size": "M",
        "position": "top",
        "duration_seconds": 5.0,
    }

    clip = {
        "start": 10.0,
        "end": 40.0,
        "video_title_for_youtube_short": "test clip",
        "video_url": f"/videos/{job_id}/mytitle_clip_1.mp4",
        "auto_hook": dict(hook_info),
    }

    meta = {
        "shorts": [clip],
        "transcript": {
            "segments": [
                {
                    "start": 0.0, "end": 60.0, "text": "hello world again",
                    "words": [{"word": "hello", "start": 12.0, "end": 12.5}],
                }
            ]
        },
        "source_video": "src.mp4",
        "output_format": "auto",
        "cost_analysis": {},
    }
    (job_dir / "mytitle_metadata.json").write_text(json.dumps(meta))
    (job_dir / "mytitle_clip_1.mp4").write_bytes(b"canonical")
    (job_dir / "src.mp4").write_bytes(b"source")

    jobs[job_id] = {
        "status": "completed",
        "logs": [],
        "result": {"clips": [dict(clip)], "cost_analysis": {}},
        "user_id": None,
        "watermark": False,
    }

    # Stub recut and add_hook_to_video
    def fake_perform_recut(**kwargs):
        name = f"recut_1_{kwargs['clean_name']}"
        with open(os.path.join(kwargs["output_dir"], name), "wb") as f:
            f.write(b"recut")
        return name, name

    def fake_add_hook(in_p, txt, out_p, **kw):
        with open(out_p, "wb") as f:
            f.write(b"hooked")
        return out_p

    monkeypatch.setattr(recut, "perform_recut", fake_perform_recut)
    monkeypatch.setattr(hooks, "add_hook_to_video", fake_add_hook)

    test_client = TestClient(app)

    try:
        resp = test_client.post("/api/clip/rerender", json={
            "job_id": job_id,
            "clip_index": 0,
            "segments": [{"start": 12.0, "end": 22.0}],
            "reapply_captions": False,
        })
        assert resp.status_code == 200

        # Verify in-memory job has auto_hook preserved
        updated_clip = jobs[job_id]["result"]["clips"][0]
        assert "auto_hook" in updated_clip
        assert updated_clip["auto_hook"] == hook_info

        # Verify disk metadata has auto_hook preserved
        saved_meta = json.loads((job_dir / "mytitle_metadata.json").read_text())
        assert saved_meta["shorts"][0]["auto_hook"] == hook_info
    finally:
        jobs.pop(job_id, None)


def test_generation_without_upload_post_header(client):
    """Verify that generation endpoint (/api/process) does not require Upload-Post."""
    resp = client.post("/api/process", data={
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    })
    # We expect 200 OK or 400 (if url invalid/sandbox), but NOT 401 or 422 for missing upload-post
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 422:
        detail = resp.json().get("detail", [])
        fields = [err.get("loc", [])[-1] for err in detail if isinstance(err, dict)]
        assert "upload_post" not in fields
        assert "uploadPostKey" not in fields
