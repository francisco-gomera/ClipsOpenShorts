"""Persistent username/password auth for self-hosted installs.

Cloud mode keeps using cloud.auth. This module is deliberately isolated from
that account and billing model and stores local accounts in a small SQLite DB.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

ACCESS_TTL_SECONDS = 15 * 60
REFRESH_TTL_SECONDS = 7 * 24 * 60 * 60
REFRESH_COOKIE = "os_refresh"
INITIAL_ADMIN_USERNAME = "francisco082"
PASSWORDS = PasswordHasher()
router = APIRouter()
_login_attempts: dict[str, list[float]] = {}


def enabled() -> bool:
    return not _flag("BILLING_ENABLED") and _flag("LOCAL_AUTH_ENABLED", "true")


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters.")
    return secret


def _db_path() -> Path:
    return Path(os.getenv("AUTH_DB_PATH", str(Path(__file__).resolve().parent / "data" / "auth.sqlite3")))


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _password_hash(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(status_code=400, detail="Passwords must contain 12 to 128 characters.")
    return PASSWORDS.hash(password)


def initialize():
    """Create additive local-auth tables and seed the one initial admin."""
    _secret()
    with _db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS local_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','user')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                auth_version INTEGER NOT NULL DEFAULT 0,
                access_expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS local_refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES local_users(id) ON DELETE CASCADE,
                family_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                replaced_by TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_local_refresh_user
                ON local_refresh_tokens(user_id, family_id);
        """)
        db.execute("DELETE FROM local_refresh_tokens WHERE expires_at<=?", (_now().isoformat(),))
        username = INITIAL_ADMIN_USERNAME
        found = db.execute("SELECT id FROM local_users WHERE username=?", (username,)).fetchone()
        if not found:
            password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
            if not password:
                raise RuntimeError(
                    "Set INITIAL_ADMIN_PASSWORD before starting self-hosted mode; "
                    "it is used only to create the initial francisco082 admin account."
                )
            if len(password) < 8 or len(password) > 128:
                raise RuntimeError("INITIAL_ADMIN_PASSWORD must contain 8 to 128 characters.")
            db.execute(
                "INSERT INTO local_users(id,username,password_hash,role,is_active,created_at,must_change_password,auth_version,access_expires_at) "
                "VALUES (?, ?, ?, 'admin', 1, ?, 1, 0, NULL)",
                (str(uuid.uuid4()), username, PASSWORDS.hash(password), _now().isoformat()),
            )
        row = db.execute("SELECT id FROM local_users WHERE username=?", (username,)).fetchone()
        return row["id"]


def _user_payload(row) -> dict:
    return {
        "id": row["id"], "username": row["username"], "role": row["role"],
        "is_active": bool(row["is_active"]), "created_at": row["created_at"],
        "must_change_password": bool(row["must_change_password"]),
        "access_expires_at": row["access_expires_at"],
    }


def _token(row) -> str:
    now = _now()
    return jwt.encode({
        "sub": row["id"], "username": row["username"], "role": row["role"],
        "ver": row["auth_version"],
        "exp": now + timedelta(seconds=ACCESS_TTL_SECONDS), "iat": now,
        "jti": secrets.token_urlsafe(12),
    }, _secret(), algorithm="HS256")


def _cookie_secure(request: Request) -> bool:
    value = os.getenv("AUTH_COOKIE_SECURE")
    if value is not None:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return request.url.scheme == "https" or os.getenv("PUBLIC_API_URL", "").startswith("https://")


def _set_refresh_cookie(response: Response, token: str, request: Request):
    response.set_cookie(REFRESH_COOKIE, token, max_age=REFRESH_TTL_SECONDS,
                        path="/api/auth", httponly=True, secure=_cookie_secure(request),
                        samesite="lax")


def _issue_refresh(db, user_id: str, family_id: str | None = None) -> str:
    raw = secrets.token_urlsafe(48)
    db.execute(
        "INSERT INTO local_refresh_tokens(token_hash,user_id,family_id,expires_at,created_at) "
        "VALUES(?,?,?,?,?)",
        (hashlib.sha256(raw.encode()).hexdigest(), user_id, family_id or str(uuid.uuid4()),
         (_now() + timedelta(seconds=REFRESH_TTL_SECONDS)).isoformat(), _now().isoformat()),
    )
    return raw


def _revoke_all(db, user_id: str):
    db.execute("UPDATE local_refresh_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
               (_now().isoformat(), user_id))


def _verified_user(request: Request):
    token = request.headers.get("authorization", "")
    token = token[7:].strip() if token.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
        user_id = claims["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    with _db() as db:
        row = db.execute("SELECT * FROM local_users WHERE id=?", (user_id,)).fetchone()
        if row is None or claims.get("ver") != row["auth_version"] or not row["is_active"]:
            raise HTTPException(status_code=401, detail="Account is inactive.")
        expiry = row["access_expires_at"]
        if expiry and datetime.fromisoformat(expiry) <= _now():
            db.execute("UPDATE local_users SET is_active=0 WHERE id=?", (user_id,))
            raise HTTPException(status_code=401, detail="Account access has expired.")
        user = _user_payload(row)
    if user["must_change_password"] and request.url.path not in {
        "/api/auth/me", "/api/auth/change-password", "/api/auth/logout", "/api/auth/refresh",
    }:
        raise HTTPException(status_code=403, detail="Change your initial password to continue.")
    return user


def local_auth_middleware_enabled(request: Request) -> bool:
    if not enabled():
        return False
    if request.method == "OPTIONS":
        return False
    path = request.url.path
    if path == "/mcp":
        return request.method == "POST"
    if not path.startswith("/api/"):
        return False
    if path in {"/api/config", "/api/auth/login", "/api/auth/refresh", "/api/auth/logout"}:
        return False
    if path.startswith("/api/source/"):
        return False  # that endpoint validates its short-lived signed media URL
    if path.startswith("/api/tools/"):
        return False  # deliberately public utility endpoints
    return True


def authenticate_request(request: Request):
    user = _verified_user(request)
    request.state.local_user = user
    return user


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


@router.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < 900]
    if len(attempts) >= 8:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    with _db() as db:
        row = db.execute("SELECT * FROM local_users WHERE username=? COLLATE NOCASE",
                         (payload.username.strip(),)).fetchone()
        valid = bool(row and row["is_active"])
        if valid and row["access_expires_at"] and datetime.fromisoformat(row["access_expires_at"]) <= _now():
            db.execute("UPDATE local_users SET is_active=0 WHERE id=?", (row["id"],))
            valid = False
        if valid:
            try:
                PASSWORDS.verify(row["password_hash"], payload.password)
            except Exception:
                valid = False
        if not valid:
            attempts.append(now)
            _login_attempts[ip] = attempts
            raise HTTPException(status_code=401, detail="Incorrect username or password.")
        _login_attempts.pop(ip, None)
        refresh = _issue_refresh(db, row["id"])
        access = _token(row)
        user = _user_payload(row)
    _set_refresh_cookie(response, refresh, request)
    return {"access_token": access, "token_type": "bearer", "user": user}


@router.post("/api/auth/refresh")
def refresh_session(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE, "")
    if not raw:
        raise HTTPException(status_code=401, detail="Refresh session expired. Sign in again.")
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM local_refresh_tokens WHERE token_hash=?", (token_hash,)).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Refresh session is invalid.")
        if row["revoked_at"]:
            db.execute("UPDATE local_refresh_tokens SET revoked_at=? WHERE family_id=? AND revoked_at IS NULL",
                       (_now().isoformat(), row["family_id"]))
            db.commit()
            raise HTTPException(status_code=401, detail="Refresh session reuse detected. Sign in again.")
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            db.execute("UPDATE local_refresh_tokens SET revoked_at=? WHERE token_hash=?",
                       (_now().isoformat(), token_hash))
            db.commit()
            raise HTTPException(status_code=401, detail="Refresh session expired. Sign in again.")
        user_row = db.execute("SELECT * FROM local_users WHERE id=?", (row["user_id"],)).fetchone()
        if not user_row or not user_row["is_active"] or (
                user_row["access_expires_at"] and datetime.fromisoformat(user_row["access_expires_at"]) <= _now()):
            _revoke_all(db, row["user_id"])
            db.commit()
            raise HTTPException(status_code=401, detail="Account is inactive or expired.")
        new_refresh = _issue_refresh(db, row["user_id"], row["family_id"])
        new_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
        db.execute("UPDATE local_refresh_tokens SET revoked_at=?, replaced_by=? WHERE token_hash=?",
                   (_now().isoformat(), new_hash, token_hash))
        user = _user_payload(user_row)
        access = _token(user_row)
    _set_refresh_cookie(response, new_refresh, request)
    return {"access_token": access, "token_type": "bearer", "user": user}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE, "")
    if raw:
        with _db() as db:
            db.execute("UPDATE local_refresh_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                       (_now().isoformat(), hashlib.sha256(raw.encode()).hexdigest()))
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth", httponly=True,
                           secure=_cookie_secure(request), samesite="lax")
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    return {"user": authenticate_request(request)}


@router.post("/api/auth/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, response: Response):
    user = authenticate_request(request)
    with _db() as db:
        row = db.execute("SELECT * FROM local_users WHERE id=?", (user["id"],)).fetchone()
        try:
            PASSWORDS.verify(row["password_hash"], payload.current_password)
        except Exception:
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        new_hash = _password_hash(payload.new_password)
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE local_users SET password_hash=?,must_change_password=0,auth_version=auth_version+1 WHERE id=?",
                   (new_hash, user["id"]))
        _revoke_all(db, user["id"])
        updated = db.execute("SELECT * FROM local_users WHERE id=?", (user["id"],)).fetchone()
        refresh = _issue_refresh(db, user["id"])
        access = _token(updated)
        out_user = _user_payload(updated)
    _set_refresh_cookie(response, refresh, request)
    return {"access_token": access, "user": out_user}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)
    role: str = "user"
    access_expires_at: datetime | None = None


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    access_expires_at: datetime | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=12, max_length=128)


def _admin(request: Request):
    user = authenticate_request(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


def _active_admin_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM local_users WHERE role='admin' AND is_active=1 "
                       "AND (access_expires_at IS NULL OR access_expires_at>?)",
                       (_now().isoformat(),)).fetchone()[0]


@router.get("/api/admin/users")
def list_users(request: Request, q: str = "", role: str = "", active: str = ""):
    _admin(request)
    sql, values = "SELECT * FROM local_users WHERE username LIKE ?", [f"%{q.strip()}%"]
    if role in {"admin", "user"}:
        sql += " AND role=?"; values.append(role)
    if active in {"true", "false"}:
        sql += " AND is_active=?"; values.append(1 if active == "true" else 0)
    sql += " ORDER BY username COLLATE NOCASE"
    with _db() as db:
        expired = db.execute("SELECT id FROM local_users WHERE is_active=1 AND access_expires_at IS NOT NULL AND access_expires_at<=?",
                             (_now().isoformat(),)).fetchall()
        for row in expired:
            db.execute("UPDATE local_users SET is_active=0 WHERE id=?", (row["id"],))
            _revoke_all(db, row["id"])
        rows = db.execute(sql, values).fetchall()
    return {"users": [_user_payload(row) for row in rows]}


@router.post("/api/admin/users")
def create_user(payload: UserCreate, request: Request):
    _admin(request)
    if payload.role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Role must be admin or user.")
    password_hash = _password_hash(payload.password)
    expiry = _iso(payload.access_expires_at)
    if expiry and datetime.fromisoformat(expiry) <= _now():
        raise HTTPException(status_code=400, detail="Access expiration must be in the future.")
    uid = str(uuid.uuid4())
    try:
        with _db() as db:
            db.execute("INSERT INTO local_users(id,username,password_hash,role,is_active,created_at,must_change_password,auth_version,access_expires_at) "
                       "VALUES(?,?,?,?,1,?,1,0,?)",
                       (uid, payload.username, password_hash, payload.role, _now().isoformat(), expiry))
            row = db.execute("SELECT * FROM local_users WHERE id=?", (uid,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That username already exists.")
    return {"user": _user_payload(row)}


@router.patch("/api/admin/users/{user_id}")
def update_user(user_id: str, payload: UserUpdate, request: Request):
    _admin(request)
    fields = payload.model_fields_set
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM local_users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found.")
        role = payload.role if "role" in fields else row["role"]
        is_active = payload.is_active if "is_active" in fields else bool(row["is_active"])
        expiry = _iso(payload.access_expires_at) if "access_expires_at" in fields else row["access_expires_at"]
        if role not in {"admin", "user"}:
            raise HTTPException(status_code=400, detail="Role must be admin or user.")
        if row["username"].casefold() == INITIAL_ADMIN_USERNAME.casefold() and (
                role != "admin" or not is_active):
            raise HTTPException(status_code=409, detail="The bootstrap administrator must remain active with the admin role.")
        if row["username"].casefold() == INITIAL_ADMIN_USERNAME.casefold() and expiry:
            raise HTTPException(status_code=409, detail="The bootstrap administrator cannot have an access expiration.")
        if expiry and datetime.fromisoformat(expiry) <= _now():
            is_active = False
        would_remove_admin = row["role"] == "admin" and row["is_active"] and (
            role != "admin" or not is_active or (expiry and datetime.fromisoformat(expiry) <= _now()))
        if would_remove_admin and _active_admin_count(db) <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove or disable the last active administrator.")
        changed_auth = role != row["role"] or bool(row["is_active"]) != bool(is_active)
        db.execute("UPDATE local_users SET role=?,is_active=?,access_expires_at=?,auth_version=auth_version+? WHERE id=?",
                   (role, int(is_active), expiry, int(changed_auth), user_id))
        if not is_active or role != row["role"]:
            _revoke_all(db, user_id)
        updated = db.execute("SELECT * FROM local_users WHERE id=?", (user_id,)).fetchone()
    return {"user": _user_payload(updated)}


@router.post("/api/admin/users/{user_id}/reset-password")
def reset_password(user_id: str, payload: PasswordReset, request: Request):
    _admin(request)
    password_hash = _password_hash(payload.password)
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM local_users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(status_code=404, detail="User not found.")
        db.execute("UPDATE local_users SET password_hash=?,must_change_password=1,auth_version=auth_version+1 WHERE id=?",
                   (password_hash, user_id))
        _revoke_all(db, user_id)
    return {"ok": True}
