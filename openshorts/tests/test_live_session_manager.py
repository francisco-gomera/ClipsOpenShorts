import json
import os
import subprocess
import sys
import threading
import time

import pytest

from live.session import (LiveSessionManager, SessionConflict, _proc_start_time,
                          _trim_candidate_history,
                          read_state, update_state, write_state)


class FakeProcess:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


def test_candidate_history_keeps_active_items_and_latest_terminal_items():
    state = {"candidates": [{"id": str(index), "status": "completado"}
                             for index in range(500)]
             + [{"id": "active", "status": "evaluando"}]}
    _trim_candidate_history(state)

    assert len(state["candidates"]) == 51
    ids = {item["id"] for item in state["candidates"]}
    assert "active" in ids
    assert "0" not in ids
    assert "499" in ids


def test_manager_launches_isolated_worker_and_records_owner(tmp_path):
    launched = {}

    def fake_popen(command, **kwargs):
        launched.update(command=command, **kwargs)
        return FakeProcess()

    manager = LiveSessionManager(tmp_path / "output", worker_path=tmp_path / "worker.py",
                                 popen=fake_popen)
    state = manager.create("https://youtube.com/live/example", user_id="user-123")
    session_dir = tmp_path / "output" / state["id"]

    assert state["status"] == "iniciando"
    assert (session_dir / ".owner").read_text() == "user-123"
    assert launched["start_new_session"] is True
    assert launched["env"]["LIVE_SESSION_ID"] == state["id"]
    assert launched["env"]["CLIP_WORKERS"] == "1"
    assert launched["env"]["LIVE_CLIP_MIN"] == "30"
    assert launched["env"]["LIVE_CLIP_MAX"] == "60"
    assert read_state(session_dir)["min_clip_seconds"] == 30
    assert read_state(session_dir)["max_clip_seconds"] == 60
    assert manager.get(state["id"])["id"] == state["id"]
    assert manager.stop(state["id"], "detener_ya")["status"] == "deteniendo"
    assert (session_dir / "stop.request").read_text() == "detener_ya"


def test_sessions_keep_independent_clip_ranges_in_state_and_worker_environment(tmp_path):
    launched = []

    def fake_popen(command, **kwargs):
        launched.append(kwargs["env"])
        return FakeProcess()

    manager = LiveSessionManager(tmp_path / "output", worker_path=tmp_path / "worker.py",
                                 popen=fake_popen)
    first = manager.create("https://youtube.com/live/one", min_clip_seconds=30,
                           max_clip_seconds=60)
    manager.stop(first["id"], "detener_ya")
    manager._processes[first["id"]].returncode = 0
    second = manager.create("https://youtube.com/live/two", min_clip_seconds=90,
                            max_clip_seconds=120)

    assert (first["min_clip_seconds"], first["max_clip_seconds"]) == (30, 60)
    assert (second["min_clip_seconds"], second["max_clip_seconds"]) == (90, 120)
    assert (launched[0]["LIVE_CLIP_MIN"], launched[0]["LIVE_CLIP_MAX"]) == ("30", "60")
    assert (launched[1]["LIVE_CLIP_MIN"], launched[1]["LIVE_CLIP_MAX"]) == ("90", "120")
    assert read_state(tmp_path / "output" / first["id"])["max_clip_seconds"] == 60
    assert read_state(tmp_path / "output" / second["id"])["max_clip_seconds"] == 120


@pytest.mark.parametrize("minimum,maximum", [(9, 30), (30, 241), (61, 60), (30.5, 60)])
def test_manager_rejects_invalid_clip_ranges_before_launch(tmp_path, minimum, maximum):
    launches = []
    manager = LiveSessionManager(tmp_path / "output", popen=lambda *_args, **_kwargs: launches.append(True))

    with pytest.raises(ValueError):
        manager.create("https://youtube.com/live/example", min_clip_seconds=minimum,
                       max_clip_seconds=maximum)

    assert launches == []


def test_manager_marks_interrupted_sessions_stopped_on_restart(tmp_path):
    output = tmp_path / "output"
    session_id = "11111111-2222-4333-8444-555555555555"
    directory = output / session_id
    write_state(directory, {"id": session_id, "status": "capturando", "clips": []})

    manager = LiveSessionManager(output, popen=lambda *_args, **_kwargs: FakeProcess())

    assert read_state(directory)["status"] == "detenido"
    assert "reiniciar" in read_state(directory)["mensaje"]


def test_recovery_marks_inflight_render_as_error_and_pending_render_as_cancelled(tmp_path):
    output = tmp_path / "output"
    session_id = "11111111-2222-4333-8444-555555555555"
    directory = output / session_id
    write_state(directory, {"id": session_id, "status": "capturando", "clips": [],
                           "queue": [
                               {"id": "live_000001", "status": "renderizando",
                                "phase": "cortando_fragmento"},
                               {"id": "live_000002", "status": "en_cola"},
                           ]})

    LiveSessionManager(output, popen=lambda *_args, **_kwargs: FakeProcess())
    recovered = read_state(directory)

    assert recovered["queue"][0]["status"] == "error"
    assert recovered["queue"][0]["failed_phase"] == "cortando_fragmento"
    assert recovered["queue"][1]["status"] == "cancelado"


def test_active_lock_is_kept_until_worker_process_exits(tmp_path):
    manager = LiveSessionManager(tmp_path / "output", popen=lambda *_args, **_kwargs: FakeProcess())
    first = manager.create("https://youtube.com/live/one")
    with pytest.raises(SessionConflict) as conflict:
        manager.create("https://youtube.com/live/two")
    assert conflict.value.state["id"] == first["id"]

    manager.stop(first["id"], "detener_ya")
    assert manager.active_session()["status"] == "deteniendo"
    with pytest.raises(SessionConflict):
        manager.create("https://youtube.com/live/two")

    manager._processes[first["id"]].returncode = 0
    assert manager.active_session() is None
    assert manager.get(first["id"])["status"] == "error"


def test_auth_expiration_requests_stop_and_retains_lock_until_worker_exit(tmp_path):
    checked = threading.Event()
    process = FakeProcess()
    manager = LiveSessionManager(tmp_path / "output", popen=lambda *_args, **_kwargs: process,
                                 auth_checker=lambda _state: (checked.set() or False),
                                 auth_check_interval=1)
    state = manager.create("https://youtube.com/live/one", user_id="user-1",
                           auth_context={"type": "local", "session_ref": "family-1"})
    assert checked.wait(3)
    deadline = time.time() + 2
    while not (tmp_path / "output" / state["id"] / "stop.request").exists() and time.time() < deadline:
        time.sleep(0.02)
    assert (tmp_path / "output" / state["id"] / "stop.request").read_text() == "detener_ya"
    assert manager.active_session()["status"] == "deteniendo"
    assert read_state(tmp_path / "output" / state["id"])["end_reason"] == "auth_expired"
    process.returncode = 0
    assert manager.get(state["id"])["status"] == "detenido"


def test_indeterminate_auth_check_does_not_stop_live_worker(tmp_path):
    checked = threading.Event()
    process = FakeProcess()
    manager = LiveSessionManager(tmp_path / "output", popen=lambda *_args, **_kwargs: process,
                                 auth_checker=lambda _state: (checked.set() and None),
                                 auth_check_interval=1)
    state = manager.create("https://youtube.com/live/one", user_id="user-1",
                           auth_context={"type": "local", "session_ref": "family-1"})
    assert checked.wait(3)
    time.sleep(0.05)
    assert not (tmp_path / "output" / state["id"] / "stop.request").exists()
    assert manager.active_session()["id"] == state["id"]
    process.returncode = 0


def test_restart_stops_only_a_verified_worker_from_the_previous_server(tmp_path):
    if not os.path.isdir("/proc"):
        pytest.skip("Process identity verification uses Linux /proc in Docker deployments")
    session_id = "33333333-4444-4333-8444-555555555555"
    output = tmp_path / "output"
    directory = output / session_id
    directory.mkdir(parents=True)
    worker = tmp_path / "live_worker.py"
    worker.write_text("import time\nwhile True: time.sleep(1)\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["LIVE_SESSION_ID"] = session_id
    process = subprocess.Popen([sys.executable, str(worker)], env=environment, start_new_session=True)
    try:
        write_state(directory, {"id": session_id, "status": "capturando", "clips": [],
                               "worker_pid": process.pid,
                               "worker_proc_start": _proc_start_time(process.pid)})

        manager = LiveSessionManager(output, worker_path=worker)

        assert process.wait(timeout=5) is not None
        recovered = read_state(directory)
        assert recovered["status"] == "detenido"
        assert recovered["end_reason"] == "server_recovery"
        assert manager.active_session() is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_manager_rejects_path_like_session_ids(tmp_path):
    manager = LiveSessionManager(tmp_path / "output")
    with pytest.raises(FileNotFoundError):
        manager.get("../outside")


def test_worker_state_writes_preserve_user_metadata_edits(tmp_path):
    directory = tmp_path / "live"
    initial = {"id": "x", "clips": [{"video_title_for_youtube_short": "Original",
                                        "video_description_for_youtube_short": "YT original",
                                        "video_description_for_tiktok": "TikTok original",
                                        "viral_hook_text": "Hook"}]}
    write_state(directory, initial)
    update_state(directory, lambda state: state["clips"][0].update(
        viral_hook_text="Editado", video_description_for_youtube_short="YT editado",
        metadata_edited_at=123))
    stale = {"id": "x", "status": "capturando", "clips": [
        {"video_title_for_youtube_short": "Original", "viral_hook_text": "Hook"}]}

    write_state(directory, stale)

    saved = read_state(directory)
    assert saved["clips"][0]["viral_hook_text"] == "Editado"
    assert saved["clips"][0]["video_description_for_youtube_short"] == "YT editado"
    assert saved["clips"][0]["video_description_for_tiktok"] == "TikTok original"
    assert saved["status"] == "capturando"


def test_worker_state_preserves_metadata_by_clip_identity_after_reordering(tmp_path):
    directory = tmp_path / "live"
    write_state(directory, {"id": "x", "clips": [
        {"source_window_id": "candidate-a", "file": "a.mp4", "video_title_for_youtube_short": "A"},
        {"source_window_id": "candidate-b", "file": "b.mp4", "video_title_for_youtube_short": "B"},
    ]})
    update_state(directory, lambda state: state["clips"][0].update(
        video_description_for_youtube_short="Descripción editada A", metadata_edited_at=10))

    write_state(directory, {"id": "x", "status": "capturando", "clips": [
        {"source_window_id": "candidate-b", "file": "b.mp4", "video_title_for_youtube_short": "B nuevo"},
        {"source_window_id": "candidate-a", "file": "a.mp4", "video_title_for_youtube_short": "A nuevo"},
    ]})

    clips = read_state(directory)["clips"]
    by_id = {clip["source_window_id"]: clip for clip in clips}
    assert by_id["candidate-a"]["video_description_for_youtube_short"] == "Descripción editada A"
    assert "video_description_for_youtube_short" not in by_id["candidate-b"]
    assert by_id["candidate-a"]["video_title_for_youtube_short"] == "A"


def test_concurrent_partial_metadata_edits_stay_on_their_own_clips(tmp_path):
    directory = tmp_path / "live"
    write_state(directory, {"id": "x", "clips": [
        {"source_window_id": "candidate-a", "video_description_for_tiktok": "A TikTok"},
        {"source_window_id": "candidate-b", "video_description_for_tiktok": "B TikTok"},
    ]})
    barrier = threading.Barrier(2)

    def edit(index, key, value):
        barrier.wait()
        def apply(state):
            state["clips"][index][key] = value
            state["clips"][index]["metadata_edited_at"] = time.time()
        update_state(directory, apply)

    first = threading.Thread(target=edit, args=(0, "video_description_for_instagram", "A IG"))
    second = threading.Thread(target=edit, args=(1, "video_description_for_youtube_short", "B YT"))
    first.start(); second.start()
    first.join(timeout=5); second.join(timeout=5)

    clips = read_state(directory)["clips"]
    assert clips[0]["video_description_for_instagram"] == "A IG"
    assert clips[0]["video_description_for_tiktok"] == "A TikTok"
    assert "video_description_for_youtube_short" not in clips[0]
    assert clips[1]["video_description_for_youtube_short"] == "B YT"
    assert clips[1]["video_description_for_tiktok"] == "B TikTok"
    assert "video_description_for_instagram" not in clips[1]
