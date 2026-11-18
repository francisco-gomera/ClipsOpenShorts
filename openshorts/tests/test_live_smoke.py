"""L0 import and health contract for the live API scaffold."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from live_api import router


def test_live_health_endpoint():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/live/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "fase": "L6"}
