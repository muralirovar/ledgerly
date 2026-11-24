"""Built-in sign-in: username and password plus a 6-digit authenticator-app code (TOTP, RFC 6238).

Everything is standard library. Passwords are salted and hashed with scrypt, recovery codes are stored
as hashes, five wrong attempts lock the account for 15 minutes, and a code can be used only once.
The authenticator secret is stored in the database as is, so turn on FileVault for the disk.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from . import db

MIN_PASSWORD = 12
MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
ISSUER = "Ledgerly"

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_users (
    username TEXT PRIMARY KEY,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    totp_secret TEXT,
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    is_owner INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    must_change INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_totp_step INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS recovery_codes (
    username TEXT NOT NULL REFERENCES app_users(username) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at TEXT
);
"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def clean_username(value: str | None) -> str:
    return (value or "").strip().lower()


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(check.hex(), digest)
    except Exception:
        return False


_DUMMY_HASH = hash_password("not-a-real-password")


def password_problem(password: str, username: str = "") -> str:
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A few random words make a good password."
    if username and password.lower() == username.lower():
        return "The password cannot be the same as the username."
    if password.lower() in {"password1234", "123456789012", "qwertyuiop12"}:
        return "That password is too common."
    return ""


# ---------- one-time codes (TOTP) ----------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(value).zfill(digits)


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((time.time() if at is None else at) // 30))


def matching_step(secret: str, code: str, at: float | None = None) -> int | None:
    """The 30-second step the code belongs to (this one or a neighbour), else None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    now_step = int((time.time() if at is None else at) // 30)
    for step in (now_step, now_step - 1, now_step + 1):
        if hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def provisioning_uri(username: str, secret: str) -> str:
    return f"otpauth://totp/{quote(ISSUER)}:{quote(username)}?secret={secret}&issuer={quote(ISSUER)}&digits=6&period=30"


def qr_png(uri: str) -> bytes:
    import io
    import segno
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="png", scale=6, border=2)
    return buffer.getvalue()


# ---------- recovery codes ----------

def _code_hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def new_recovery_codes(connection: sqlite3.Connection, username: str, count: int = 8) -> list[str]:
    """Replace the user's recovery codes. The plain codes are returned once and never stored."""
    username = clean_username(username)
    connection.execute("DELETE FROM recovery_codes WHERE username = ?", (username,))
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
        connection.execute("INSERT INTO recovery_codes(username, code_hash) VALUES (?, ?)",
                           (username, _code_hash(codes[-1])))
    return codes


def _use_recovery_code(connection: sqlite3.Connection, username: str, code: str) -> bool:
    row = connection.execute(
        "SELECT rowid FROM recovery_codes WHERE username = ? AND code_hash = ? AND used_at IS NULL",
        (username, _code_hash(code))).fetchone()
    if not row:
        return False
    connection.execute("UPDATE recovery_codes SET used_at = ? WHERE rowid = ?", (db.utc_now(), row["rowid"]))
    return True


def recovery_codes_left(connection: sqlite3.Connection, username: str) -> int:
    return connection.execute("SELECT COUNT(*) FROM recovery_codes WHERE username = ? AND used_at IS NULL",
                              (clean_username(username),)).fetchone()[0]


# ---------- users ----------

def user_count(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM app_users").fetchone()[0]


def get_user(connection: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM app_users WHERE username = ?", (clean_username(username),)).fetchone()
    return dict(row) if row else None


def create_user(connection: sqlite3.Connection, username: str, password: str, *, display_name: str = "",
                is_owner: bool = False, must_change: bool = False) -> None:
    username = clean_username(username)
    if not username or len(username) < 3 or " " in username:
        raise ValueError("Choose a username of at least 3 characters with no spaces.")
    problem = password_problem(password, username)
    if problem:
        raise ValueError(problem)
    if get_user(connection, username):
        raise ValueError("That username is already taken.")
    connection.execute(
        """INSERT INTO app_users(username, display_name, password_hash, is_owner, must_change, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username, display_name.strip() or username, hash_password(password), int(is_owner), int(must_change), db.utc_now()))


def enable_mfa(connection: sqlite3.Connection, username: str, secret: str, code: str) -> list[str]:
    """Turn MFA on after the user proves their app shows the right code. Returns fresh recovery codes."""
    step = matching_step(secret, code)
    if step is None:
        raise ValueError("That code is not right. Check the 6 digits in your authenticator app and try again.")
    username = clean_username(username)
    connection.execute("UPDATE app_users SET totp_secret = ?, mfa_enabled = 1, last_totp_step = ? WHERE username = ?",
                       (secret, step, username))
    return new_recovery_codes(connection, username)


def set_password(connection: sqlite3.Connection, username: str, password: str, *, must_change: bool = False) -> None:
    username = clean_username(username)
    problem = password_problem(password, username)
    if problem:
        raise ValueError(problem)
    connection.execute(
        "UPDATE app_users SET password_hash = ?, must_change = ?, failed_attempts = 0, locked_until = NULL WHERE username = ?",
        (hash_password(password), int(must_change), username))


def reset_mfa(connection: sqlite3.Connection, username: str) -> None:
    username = clean_username(username)
    connection.execute("UPDATE app_users SET totp_secret = NULL, mfa_enabled = 0, last_totp_step = 0 WHERE username = ?", (username,))
    connection.execute("DELETE FROM recovery_codes WHERE username = ?", (username,))


def set_active(connection: sqlite3.Connection, username: str, active: bool) -> None:
    connection.execute("UPDATE app_users SET active = ? WHERE username = ?", (int(active), clean_username(username)))


def delete_user(connection: sqlite3.Connection, username: str) -> None:
    username = clean_username(username)
    user = get_user(connection, username)
    if user and user["is_owner"] and connection.execute(
            "SELECT COUNT(*) FROM app_users WHERE is_owner = 1 AND active = 1").fetchone()[0] <= 1:
        raise ValueError("You cannot remove the only owner.")
    connection.execute("DELETE FROM recovery_codes WHERE username = ?", (username,))
    connection.execute("DELETE FROM app_users WHERE username = ?", (username,))


def list_accounts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(
        """SELECT username, display_name, is_owner, active, mfa_enabled, must_change, last_login, locked_until
           FROM app_users ORDER BY is_owner DESC, username""")]


# ---------- sign-in ----------

def attempt_login(connection: sqlite3.Connection, username: str, password: str, code: str) -> tuple[str, dict[str, Any] | None]:
    """Check a sign-in. Returns (status, user).

    Status is one of: ok, enroll (password right, MFA not set up yet or password must change),
    invalid (wrong username, password or code; deliberately not specific), locked, disabled.
    """
    username = clean_username(username)
    user = get_user(connection, username)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return "invalid", None
    now = datetime.now(timezone.utc)
    if user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > now:
        return "locked", user
    if not user["active"]:
        verify_password(password, _DUMMY_HASH)
        return "disabled", user

    def fail() -> tuple[str, dict[str, Any] | None]:
        attempts = int(user["failed_attempts"]) + 1
        locked = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") if attempts >= MAX_ATTEMPTS else None
        connection.execute("UPDATE app_users SET failed_attempts = ?, locked_until = ? WHERE username = ?",
                           (0 if locked else attempts, locked, username))
        return ("locked" if locked else "invalid"), user

    if not verify_password(password, user["password_hash"]):
        return fail()
    if not user["mfa_enabled"] or user["must_change"]:
        return "enroll", user
    step = matching_step(user["totp_secret"], code)
    if step is not None and step > int(user["last_totp_step"]):
        connection.execute("UPDATE app_users SET last_totp_step = ? WHERE username = ?", (step, username))
    elif not _use_recovery_code(connection, username, code):
        return fail()
    connection.execute("UPDATE app_users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE username = ?",
                       (db.utc_now(), username))
    return "ok", user
