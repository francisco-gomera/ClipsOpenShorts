from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import live_api
from live.session import LiveSessionManager, write_state


class FakeManager:
    def __init__(self, tmp_path):
        self.output_dir = tmp_path
        self.state = {"id": "11111111-2222-4333-8444-555555555555", "status": "capturando", "user_id": "owner-1",
                      "clips": [{"file": "live.mp4", "video_url": "/videos/11111111-2222-4333-8444-555555555555/live.mp4"}],
                      "queue": []}
        write_state(self._directory(self.state["id"]), self.state)

    def get(self, _session_id):
        return self.state

    def create(self, url, user_id=None, min_clip_seconds=30, max_clip_seconds=60):
        self.state.update(url=url, user_id=user_id, min_clip_seconds=min_clip_seconds,
                          max_clip_seconds=max_clip_seconds)
        write_state(self._directory(self.state["id"]), self.state)
        return self.state

    def stop(self, _session_id, mode):
        self.state["modo_parada"] = mode
        self.state["status"] = "deteniendo"
        return self.state

    def _directory(self, _session_id):
        directory = self.output_dir / self.state["id"]
        directory.mkdir(parents=True, exist_ok=True)
        return directory


def test_live_api_returns_owner_scoped_session_and_clip_urls(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(live_api, "_manager", manager)
    monkeypatch.setattr(live_api, "_owner_resolver", lambda _request: _async_value("owner-1"))
    monkeypatch.setattr(live_api, "_access_check", lambda _request: _async_value(None))
    monkeypatch.setattr(live_api, "_media_signer", lambda url: url + "?sig=ok")
    monkeypatch.setattr(live_api, "_validate_youtube_url", lambda _url: None)
    app = FastAPI()
    app.include_router(live_api.router)

    with TestClient(app) as client:
        created = client.post("/api/live", json={"url": "https://youtube.com/live/id"})
        fetched = client.get("/api/live/" + manager.state["id"])
        updated = client.patch("/api/live/" + manager.state["id"] + "/clips/0",
                               json={"viral_hook_text": "Gancho editado"})
        stopped = client.post("/api/live/" + manager.state["id"] + "/stop", json={"modo": "detener_ya"})

    assert created.status_code == 202
    assert created.json()["user_id"] == "owner-1"
    assert created.json()["min_clip_seconds"] == 30
    assert created.json()["max_clip_seconds"] == 60
    assert fetched.json()["clips"][0]["video_url"].endswith("?sig=ok")
    assert updated.json()["clips"][0]["viral_hook_text"] == "Gancho editado"
    assert (tmp_path / manager.state["id"] / "live_metadata.json").is_file()
    assert stopped.json()["modo_parada"] == "detener_ya"


def test_live_api_calculates_capture_elapsed_from_persisted_timestamps(monkeypatch):
    monkeypatch.setattr(live_api.time, "time", lambda: 125.9)

    active = live_api._present({"status": "reconectando", "capture_started_at": 100.0,
                                "capture_ended_at": None})
    finished = live_api._present({"status": "detenido", "capture_started_at": 100.0,
                                  "capture_ended_at": 120.0})
    never_started = live_api._present({"status": "error"})

    assert active["capture_elapsed_seconds"] == 25
    assert active["capture_ended_at"] is None
    assert finished["capture_elapsed_seconds"] == 20
    assert never_started["capture_started_at"] is None
    assert never_started["capture_elapsed_seconds"] == 0


def test_live_api_preserves_progress_fields_and_defaults_for_older_sessions():
    progress = live_api._present({
        "status": "capturando", "asr_status": "activo", "reconnections": 2,
        "render_priority_paused": True,
        "queue": [{"id": "live_000001", "status": "renderizando",
                   "phase": "cortando_fragmento", "phase_started_at": 100}],
        "notices": [{"tipo": "render_iniciado", "mensaje": "Comenzó el render", "at": 101}],
    })
    legacy = live_api._present({"status": "detenido"})

    assert progress["queue"][0]["phase"] == "cortando_fragmento"
    assert progress["render_priority_paused"] is True
    assert progress["reconnections"] == 2
    assert progress["asr_status"] == "activo"
    assert progress["notices"][0]["mensaje"] == "Comenzó el render"
    assert legacy["queue"] == []


def test_live_api_accepts_custom_clip_range_and_rejects_invalid_ranges(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(live_api, "_manager", manager)
    monkeypatch.setattr(live_api, "_owner_resolver", lambda _request: _async_value("owner-1"))
    monkeypatch.setattr(live_api, "_access_check", lambda _request: _async_value(None))
    monkeypatch.setattr(live_api, "_validate_youtube_url", lambda _url: None)
    app = FastAPI()
    app.include_router(live_api.router)

    with TestClient(app) as client:
        valid_ranges = [client.post("/api/live", json={"url": "https://youtube.com/live/id",
                                                        "min_clip_seconds": minimum,
                                                        "max_clip_seconds": maximum})
                        for minimum, maximum in ((30, 60), (10, 30), (60, 60),
                                                 (120, 240), (10, 240))]
        invalid = client.post("/api/live", json={"url": "https://youtube.com/live/id",
                                                 "min_clip_seconds": 61, "max_clip_seconds": 60})
        below_minimum = client.post("/api/live", json={"url": "https://youtube.com/live/id",
                                                        "min_clip_seconds": 9, "max_clip_seconds": 60})
        above_maximum = client.post("/api/live", json={"url": "https://youtube.com/live/id",
                                                       "min_clip_seconds": 30, "max_clip_seconds": 241})
        non_numeric = client.post("/api/live", json={"url": "https://youtube.com/live/id",
                                                     "min_clip_seconds": "rápido", "max_clip_seconds": 60})
        monkeypatch.setattr(live_api, "_validate_youtube_url",
                            lambda _url: (_ for _ in ()).throw(live_api.LiveResolveError("URL inválida")))
        invalid_url = client.post("/api/live", json={"url": "https://example.com/video",
                                                      "min_clip_seconds": 30, "max_clip_seconds": 60})

    assert all(response.status_code == 202 for response in valid_ranges)
    assert [(response.json()["min_clip_seconds"], response.json()["max_clip_seconds"])
            for response in valid_ranges] == [(30, 60), (10, 30), (60, 60), (120, 240), (10, 240)]
    assert invalid.status_code == 422
    assert below_minimum.status_code == 422
    assert above_maximum.status_code == 422
    assert non_numeric.status_code == 422
    assert invalid_url.status_code == 400


def test_live_mutations_and_reads_reject_invalid_auth_before_touching_sessions(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    created = []
    original_create = manager.create
    manager.create = lambda *args, **kwargs: (created.append(True), original_create(*args, **kwargs))[1]
    monkeypatch.setattr(live_api, "_manager", manager)
    monkeypatch.setattr(live_api, "_access_check",
                        lambda _request: _raise_unauthorized())
    app = FastAPI()
    app.include_router(live_api.router)

    with TestClient(app) as client:
        session_id = manager.state["id"]
        responses = [
            client.post("/api/live", json={"url": "https://youtube.com/live/id"}),
            client.get("/api/live"),
            client.get(f"/api/live/{session_id}"),
            client.post(f"/api/live/{session_id}/stop", json={"modo": "detener_ya"}),
            client.patch(f"/api/live/{session_id}/clips/0", json={"viral_hook_text": "x"}),
            client.get(f"/api/live/{session_id}/download/0"),
            client.get(f"/api/live/{session_id}/download.zip"),
        ]

    assert [response.status_code for response in responses] == [401] * len(responses)
    assert created == []


def test_user_cannot_access_or_stop_another_users_live_session(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(live_api, "_manager", manager)
    monkeypatch.setattr(live_api, "_owner_resolver", lambda _request: _async_value("owner-2"))
    monkeypatch.setattr(live_api, "_access_check", lambda _request: _async_value(None))
    app = FastAPI()
    app.include_router(live_api.router)

    with TestClient(app) as client:
        session_id = manager.state["id"]
        fetched = client.get(f"/api/live/{session_id}")
        stopped = client.post(f"/api/live/{session_id}/stop", json={"modo": "detener_ya"})

    assert fetched.status_code == 404
    assert stopped.status_code == 404
    assert manager.state["status"] == "capturando"


def test_active_session_conflict_is_structured_and_owner_scoped(tmp_path, monkeypatch):
    class Process:
        def poll(self):
            return None

    manager = LiveSessionManager(tmp_path, popen=lambda *_args, **_kwargs: Process())
    active = manager.create("https://youtube.com/live/active", user_id="owner-1")
    monkeypatch.setattr(live_api, "_manager", manager)
    monkeypatch.setattr(live_api, "_owner_resolver", lambda _request: _async_value("owner-1"))
    monkeypatch.setattr(live_api, "_access_check", lambda _request: _async_value(None))
    monkeypatch.setattr(live_api, "_validate_youtube_url", lambda _url: None)
    app = FastAPI()
    app.include_router(live_api.router)

    with TestClient(app) as client:
        response = client.post("/api/live", json={"url": "https://youtube.com/live/next"})

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "live_session_active", "status": "iniciando",
                                          "stopping": False, "session_id": active["id"]}


async def _async_value(value):
    return value


async def _raise_unauthorized():
    raise HTTPException(status_code=401, detail="Session expired")
