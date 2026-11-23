import json

import pytest

from live.session import LiveSessionManager, read_state, update_state, write_state


class FakeProcess:
    def poll(self):
        return None


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


def test_manager_rejects_path_like_session_ids(tmp_path):
    manager = LiveSessionManager(tmp_path / "output")
    with pytest.raises(FileNotFoundError):
        manager.get("../outside")


def test_worker_state_writes_preserve_user_metadata_edits(tmp_path):
    directory = tmp_path / "live"
    initial = {"id": "x", "clips": [{"video_title_for_youtube_short": "Original",
                                        "viral_hook_text": "Hook"}]}
    write_state(directory, initial)
    update_state(directory, lambda state: state["clips"][0].update(
        viral_hook_text="Editado", metadata_edited_at=123))
    stale = {"id": "x", "status": "capturando", "clips": [
        {"video_title_for_youtube_short": "Original", "viral_hook_text": "Hook"}]}

    write_state(directory, stale)

    saved = read_state(directory)
    assert saved["clips"][0]["viral_hook_text"] == "Editado"
    assert saved["status"] == "capturando"
