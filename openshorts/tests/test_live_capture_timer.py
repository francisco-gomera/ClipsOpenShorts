from live.session import LiveSessionManager, LiveSessionRuntime, read_state, write_state


def make_runtime(directory):
    directory.mkdir(parents=True, exist_ok=True)
    write_state(directory, {"id": "live-test", "status": "iniciando", "clips": []})
    return LiveSessionRuntime("live-test", "https://youtube.com/live/test", directory,
                             directory / "stop.request")


def test_capture_timer_starts_once_survives_reconnect_and_freezes(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("live.session.time.time", lambda: now[0])
    runtime = make_runtime(tmp_path / "session")

    state = read_state(tmp_path / "session")
    assert state["capture_started_at"] is None
    assert state["capture_ended_at"] is None
    assert state["capture_elapsed_seconds"] == 0

    runtime._status("capturando")
    assert read_state(tmp_path / "session")["capture_started_at"] == 100.0
    now[0] = 110.0
    runtime._status("reconectando")
    now[0] = 120.0
    runtime._status("capturando")
    state = read_state(tmp_path / "session")
    assert state["capture_started_at"] == 100.0
    assert state["capture_ended_at"] is None
    assert state["capture_elapsed_seconds"] == 20

    now[0] = 130.0
    runtime._capture_ended()
    now[0] = 160.0
    runtime._status("detenido")
    state = read_state(tmp_path / "session")
    assert state["capture_ended_at"] == 130.0
    assert state["capture_elapsed_seconds"] == 30


def test_error_before_first_capture_keeps_timer_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("live.session.time.time", lambda: 123.0)
    runtime = make_runtime(tmp_path / "session")

    runtime._status("error", {"error": "falló el resolver"})
    runtime._capture_ended()

    state = read_state(tmp_path / "session")
    assert state["capture_started_at"] is None
    assert state["capture_ended_at"] is None
    assert state["capture_elapsed_seconds"] == 0


def test_recovery_closes_interrupted_capture_and_migrates_old_states(tmp_path, monkeypatch):
    session_id = "11111111-2222-4333-8444-555555555555"
    directory = tmp_path / "output" / session_id
    write_state(directory, {"id": session_id, "status": "capturando", "clips": [],
                           "capture_started_at": 100.0, "capture_ended_at": None,
                           "capture_elapsed_seconds": 20})
    old_id = "22222222-3333-4333-8444-555555555555"
    old_directory = tmp_path / "output" / old_id
    write_state(old_directory, {"id": old_id, "status": "esperando", "clips": []})
    monkeypatch.setattr("live.session.time.time", lambda: 125.0)

    LiveSessionManager(tmp_path / "output", popen=lambda *_args, **_kwargs: None)

    recovered = read_state(directory)
    assert recovered["status"] == "detenido"
    assert recovered["capture_started_at"] == 100.0
    assert recovered["capture_ended_at"] == 125.0
    assert recovered["capture_elapsed_seconds"] == 25
    old = read_state(old_directory)
    assert old["capture_started_at"] is None
    assert old["capture_ended_at"] is None
    assert old["capture_elapsed_seconds"] == 0
