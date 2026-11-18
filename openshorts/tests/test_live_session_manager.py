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
    assert manager.get(state["id"])["id"] == state["id"]
    assert manager.stop(state["id"], "detener_ya")["status"] == "deteniendo"
    assert (session_dir / "stop.request").read_text() == "detener_ya"


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
