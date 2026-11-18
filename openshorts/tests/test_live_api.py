from fastapi import FastAPI
from fastapi.testclient import TestClient

import live_api
from live.session import write_state


class FakeManager:
    def __init__(self, tmp_path):
        self.output_dir = tmp_path
        self.state = {"id": "11111111-2222-4333-8444-555555555555", "status": "capturando", "user_id": "owner-1",
                      "clips": [{"file": "live.mp4", "video_url": "/videos/11111111-2222-4333-8444-555555555555/live.mp4"}],
                      "queue": []}
        write_state(self._directory(self.state["id"]), self.state)

    def get(self, _session_id):
        return self.state

    def create(self, url, user_id=None):
        self.state.update(url=url, user_id=user_id)
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
    assert fetched.json()["clips"][0]["video_url"].endswith("?sig=ok")
    assert updated.json()["clips"][0]["viral_hook_text"] == "Gancho editado"
    assert (tmp_path / manager.state["id"] / "live_metadata.json").is_file()
    assert stopped.json()["modo_parada"] == "detener_ya"


async def _async_value(value):
    return value
