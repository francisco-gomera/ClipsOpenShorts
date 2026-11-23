import asyncio

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response


def _request(method, path):
    return Request({"type": "http", "method": method, "path": path,
                    "query_string": b"", "headers": []})


def test_live_exclusivity_does_not_intercept_auth_refresh_or_logout(monkeypatch):
    import app

    monkeypatch.setattr(app._live_api, "has_active_session", lambda: True)
    called = []

    async def call_next(_request):
        called.append(True)
        return Response(status_code=200)

    refresh = asyncio.run(app.block_other_work_during_live(_request("POST", "/api/auth/refresh"), call_next))
    logout = asyncio.run(app.block_other_work_during_live(_request("POST", "/api/auth/logout"), call_next))

    assert refresh.status_code == logout.status_code == 200
    assert len(called) == 2


def test_expired_auth_is_reported_before_the_live_operation_lock(monkeypatch):
    import app

    monkeypatch.setattr(app.local_auth, "local_auth_middleware_enabled", lambda _request: True)

    def expired(_request):
        raise HTTPException(status_code=401, detail="Session expired")

    monkeypatch.setattr(app.local_auth, "authenticate_request", expired)
    monkeypatch.setattr(app._live_api, "has_active_session",
                        lambda: (_ for _ in ()).throw(AssertionError("lock should not be checked")))

    async def call_next(_request):
        raise AssertionError("unauthorized request must not reach the operation")

    response = asyncio.run(app.block_other_work_during_live(_request("POST", "/api/jobs"), call_next))
    assert response.status_code == 401
