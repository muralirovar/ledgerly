"""Which businesses each person may open, and the audit trail of who did what.

Sign-in is in :mod:`books.auth`. An owner sees every business and the admin pages; everyone else sees only the
businesses granted to their username. The role column is kept so read-only roles can be added later.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import db

ROLES = ("editor",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_access (
    username TEXT NOT NULL,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'editor',
    created_at TEXT NOT NULL,
    PRIMARY KEY (username, business_id)
);
CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    business TEXT,
    page TEXT,
    created_at TEXT NOT NULL
);
"""


def clean(value: str | None) -> str:
    return (value or "").strip().lower()


def _rename_email_columns(connection: sqlite3.Connection) -> None:
    """Early versions called the column ``email``; it now holds the username."""
    for table in ("user_access", "access_log"):
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "email" in columns and "username" not in columns:
            connection.execute(f"ALTER TABLE {table} RENAME COLUMN email TO username")


def ensure_schema(connection: sqlite3.Connection) -> None:
    _rename_email_columns(connection)
    connection.executescript(SCHEMA)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(access_log)")}
    for column in ("business", "page"):
        if column not in columns:
            connection.execute(f"ALTER TABLE access_log ADD COLUMN {column} TEXT")


def business_ids_for(connection: sqlite3.Connection, username: str) -> list[int]:
    return [int(row["business_id"]) for row in connection.execute(
        "SELECT business_id FROM user_access WHERE username = ? ORDER BY business_id", (clean(username),))]


def grant(connection: sqlite3.Connection, username: str, business_ids: list[int], role: str = "editor") -> None:
    """Make the list of businesses for this person exactly ``business_ids``."""
    username = clean(username)
    if not username:
        raise ValueError("Choose a person.")
    if role not in ROLES:
        raise ValueError("Unknown role.")
    connection.execute("DELETE FROM user_access WHERE username = ?", (username,))
    for business_id in dict.fromkeys(int(b) for b in business_ids):
        connection.execute(
            "INSERT INTO user_access(username, business_id, role, created_at) VALUES (?, ?, ?, ?)",
            (username, business_id, role, db.utc_now()))


def revoke(connection: sqlite3.Connection, username: str) -> int:
    return connection.execute("DELETE FROM user_access WHERE username = ?", (clean(username),)).rowcount


def businesses_text(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """SELECT u.username, GROUP_CONCAT(b.name, ', ') AS businesses
           FROM user_access u JOIN businesses b ON b.id = u.business_id GROUP BY u.username""").fetchall()
    return {row["username"]: row["businesses"] for row in rows}


def log(connection: sqlite3.Connection, username: str, event: str, detail: str = "",
        business: str = "", page: str = "") -> None:
    connection.execute(
        "INSERT INTO access_log(username, event, detail, business, page, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (clean(username), event, detail, business, page, db.utc_now()))


def audit(connection: sqlite3.Connection, *, username: str = "", event: str = "", business: str = "",
          since: str = "", until: str = "", limit: int = 5000) -> list[dict[str, Any]]:
    """Audit rows, newest first. Dates are YYYY-MM-DD (UTC)."""
    where, params = ["1 = 1"], []
    if username:
        where.append("username = ?")
        params.append(clean(username))
    if event:
        where.append("event = ?")
        params.append(event)
    if business:
        where.append("business = ?")
        params.append(business)
    if since:
        where.append("created_at >= ?")
        params.append(since)
    if until:
        where.append("created_at < ?")
        params.append(until + "T99")
    return [dict(row) for row in connection.execute(
        f"""SELECT created_at, username, event, business, page, detail FROM access_log
            WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?""", [*params, limit])]


def user_summary(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """One line per person: sign-ins, failures, last sign-in, last activity and the businesses they opened."""
    return [dict(row) for row in connection.execute(
        """SELECT username,
                  SUM(CASE WHEN event = 'sign in' THEN 1 ELSE 0 END) AS sign_ins,
                  SUM(CASE WHEN event IN ('failed sign in', 'locked') THEN 1 ELSE 0 END) AS failures,
                  MAX(CASE WHEN event = 'sign in' THEN created_at END) AS last_sign_in,
                  MAX(created_at) AS last_activity,
                  COUNT(CASE WHEN event = 'view' THEN 1 END) AS page_views,
                  GROUP_CONCAT(DISTINCT CASE WHEN event = 'view' THEN business END) AS businesses_opened
           FROM access_log GROUP BY username ORDER BY last_activity DESC""")]
