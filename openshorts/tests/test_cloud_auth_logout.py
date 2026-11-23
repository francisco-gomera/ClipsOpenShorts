import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
from starlette.requests import Request


def _request(token):
    return Request({"type": "http", "method": "POST", "path": "/api/auth/logout",
                    "query_string": b"", "headers": [(b"authorization", f"Bearer {token}".encode())]})


def test_cloud_logout_revokes_token_and_requests_owner_live_stop(monkeypatch):
    from cloud import auth
    import live_api

    monkeypatch.setenv("JWT_SECRET", "logout-test-secret-that-is-at-least-32-chars")
    user_id = "44444444-4444-4444-8444-444444444444"
    token = jwt.encode({"sub": user_id, "email": "person@example.com", "jti": "session-jti",
                        "iat": datetime.now(timezone.utc),
                        "exp": datetime.now(timezone.utc) + timedelta(days=1)},
                       auth.settings.jwt_secret, algorithm=auth.JWT_ALGO)
    revoked = {}
    added = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, model, key):
            if model is auth.User:
                return object()
            return revoked.get(key)

        def add(self, row):
            added.append(row)
            revoked[row.jti] = row

        async def execute(self, _statement):
            return None

    monkeypatch.setattr(auth.database, "session", lambda: FakeSession())
    stopped = []
    monkeypatch.setattr(live_api, "stop_owned_sessions",
                        lambda owner, reason: stopped.append((owner, reason)) or [])

    first = asyncio.run(auth.logout(_request(token)))
    second = asyncio.run(auth.logout(_request(token)))
    user = asyncio.run(auth.get_current_user_optional(_request(token)))

    assert first == second == {"ok": True}
    assert stopped == [(user_id, "logout"), (user_id, "logout")]
    assert len(added) == 1
    assert user is None
