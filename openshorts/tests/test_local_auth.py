import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import local_auth


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_ENABLED", "1")
    monkeypatch.setenv("BILLING_ENABLED", "0")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-jwt-signing")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "bootstrap-pass")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.sqlite3"))
    local_auth._login_attempts.clear()
    local_auth.initialize()
    app = FastAPI()

    @app.middleware("http")
    async def local_auth_guard(request, call_next):
        if local_auth.local_auth_middleware_enabled(request):
            try:
                local_auth.authenticate_request(request)
            except Exception as exc:
                from fastapi import HTTPException
                if isinstance(exc, HTTPException):
                    from fastapi.responses import JSONResponse
                    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                raise
        return await call_next(request)

    app.include_router(local_auth.router)

    @app.get("/api/private")
    def private():
        return {"ok": True}

    with TestClient(app) as test_client:
        yield test_client


def test_bootstrap_admin_forced_password_change_and_relogin(client):
    login = client.post("/api/auth/login", json={"username": "francisco082", "password": "bootstrap-pass"})
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/private", headers=headers).status_code == 403

    changed = client.post("/api/auth/change-password", json={
        "current_password": "bootstrap-pass", "new_password": "a-strong-new-password",
    }, headers=headers)
    assert changed.status_code == 200
    assert changed.json()["user"]["must_change_password"] is False
    renewed_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/api/private", headers=renewed_headers).status_code == 200
    assert client.post("/api/auth/login", json={
        "username": "francisco082", "password": "a-strong-new-password",
    }).status_code == 200


def test_refresh_rotation_and_reuse_revokes_token_family(client):
    assert client.post("/api/auth/login", json={"username": "francisco082", "password": "bootstrap-pass"}).status_code == 200
    old = client.cookies.get(local_auth.REFRESH_COOKIE)
    rotated = client.post("/api/auth/refresh")
    assert rotated.status_code == 200
    new = client.cookies.get(local_auth.REFRESH_COOKIE)
    assert new and new != old

    client.cookies.set(local_auth.REFRESH_COOKIE, old)
    assert client.post("/api/auth/refresh").status_code == 401
    client.cookies.set(local_auth.REFRESH_COOKIE, new)
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_requests_live_stop_before_revoking_and_is_idempotent(client, monkeypatch):
    stopped = []
    import live_api
    monkeypatch.setattr(live_api, "stop_owned_sessions",
                        lambda user_id, reason: stopped.append((user_id, reason)) or [])
    login = client.post("/api/auth/login", json={"username": "francisco082", "password": "bootstrap-pass"})
    assert login.status_code == 200
    user_id = login.json()["user"]["id"]

    first = client.post("/api/auth/logout")
    second = client.post("/api/auth/logout")

    assert first.status_code == second.status_code == 200
    assert first.json()["ok"] and second.json()["ok"]
    assert stopped == [(user_id, "logout")]
    assert client.get("/api/private", headers={
        "Authorization": f"Bearer {login.json()['access_token']}"
    }).status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401


def test_admin_can_create_users_and_last_admin_cannot_be_demoted(client):
    login = client.post("/api/auth/login", json={"username": "francisco082", "password": "bootstrap-pass"})
    changed = client.post("/api/auth/change-password", json={
        "current_password": "bootstrap-pass", "new_password": "a-strong-new-password",
    }, headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    admin_token = changed.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    create = client.post("/api/admin/users", headers=headers, json={
        "username": "editor", "password": "a-temporary-password", "role": "user",
    })
    assert create.status_code == 200
    user_id = create.json()["user"]["id"]
    assert client.patch(f"/api/admin/users/{user_id}", headers=headers,
                        json={"role": "admin"}).status_code == 200

    bootstrap_id = login.json()["user"]["id"]
    demote = client.patch(f"/api/admin/users/{bootstrap_id}", headers=headers,
                         json={"role": "user"})
    assert demote.status_code == 409


def test_initial_password_is_not_reset_by_later_initialization(client, monkeypatch):
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "another-bootstrap-pass")
    local_auth.initialize()
    result = client.post("/api/auth/login", json={"username": "francisco082", "password": "bootstrap-pass"})
    assert result.status_code == 200
