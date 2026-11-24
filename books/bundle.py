"""Move one business between two copies of Ledgerly as a single file (a "bundle").

A bundle is a small SQLite file holding every row that belongs to one business: accounts, categories, rules,
transactions (with splits and attachments), checks, statements, loans, staff, mileage and so on. It can be
protected with a password (Fernet, key from scrypt). Importing **replaces** that business in the target
database (or adds it when it is not there yet); other businesses are never touched. Ids are renumbered on
the way in, so the two databases do not have to agree on them.

Not included, because they are not per business: login accounts, the audit log, app settings and personal tax items.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import db

FORMAT = 1
MAGIC = b"LEDGERLY-ENC1\n"
SQLITE_MAGIC = b"SQLite format 3\x00"

# (table, how to find this business's rows, {column: table it points to})
TABLES: list[tuple[str, str, dict[str, str]]] = [
    ("accounts", "business_id = ?", {}),
    ("categories", "business_id = ?", {}),
    ("import_batches", "business_id = ?", {"account_id": "accounts"}),
    ("rules", "business_id = ?", {"account_id": "accounts", "category_id": "categories", "related_account_id": "accounts"}),
    ("transactions", "business_id = ?", {"account_id": "accounts", "category_id": "categories",
                                         "related_account_id": "accounts", "import_batch_id": "import_batches",
                                         "learned_rule_id": "rules"}),
    ("loan_events", "business_id = ?", {"loc_account_id": "accounts", "linked_transaction_id": "transactions"}),
    ("vendors", "business_id = ?", {"category_id": "categories", "rule_id": "rules"}),
    ("check_register", "business_id = ?", {"account_id": "accounts", "transaction_id": "transactions",
                                           "category_id": "categories"}),
    ("statement_log", "business_id = ?", {"account_id": "accounts"}),
    ("statement_log_checks", "log_id IN (SELECT id FROM statement_log WHERE business_id = ?)",
     {"log_id": "statement_log", "transaction_id": "transactions"}),
    ("margin_links", "business_id = ?", {}),
    ("transaction_split_log", "business_id = ?", {"parent_id": "transactions"}),
    ("transaction_attachments", "business_id = ?", {"transaction_id": "transactions"}),
    ("staff", "business_id = ?", {}),
    ("staff_rates", "staff_id IN (SELECT id FROM staff WHERE business_id = ?)", {"staff_id": "staff"}),
    ("staff_months", "staff_id IN (SELECT id FROM staff WHERE business_id = ?)", {"staff_id": "staff"}),
    ("staff_matches", "business_id = ?", {"staff_id": "staff", "transaction_id": "transactions"}),
    ("staff_payments", "business_id = ?", {"staff_id": "staff", "transaction_id": "transactions"}),
    ("revenue_picks", "business_id = ?", {"transaction_id": "transactions"}),
    ("mileage_log", "business_id = ?", {}),
]
COUNTED = ("accounts", "transactions", "categories", "rules", "check_register", "staff", "mileage_log", "loan_events",
           "transaction_attachments")


class NeedPassword(Exception):
    """The file is encrypted and no password was given."""


# ---------- encryption ----------

def _key(password: str, salt: bytes) -> bytes:
    return base64.urlsafe_b64encode(hashlib.scrypt(password.encode(), salt=salt, n=2 ** 15, r=8, p=1, dklen=32,
                                                   maxmem=128 * 1024 * 1024))


def encrypt(data: bytes, password: str) -> bytes:
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_key(password, salt)).encrypt(data)


def decrypt(data: bytes, password: str) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken
    body = data[len(MAGIC):]
    try:
        return Fernet(_key(password, body[:16])).decrypt(body[16:])
    except InvalidToken:
        raise ValueError("That password does not open this file.") from None


def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)


# ---------- export ----------

def export_bundle(connection: sqlite3.Connection, business_id: int, *, exported_by: str = "",
                  password: str = "") -> bytes:
    """One business as bytes, ready to save as ``name.ledgerly``."""
    business = connection.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if business is None:
        raise ValueError("Business not found.")
    handle, name = tempfile.mkstemp(suffix=".ledgerly")
    os.close(handle)
    try:
        target = sqlite3.connect(name)
        try:
            names = ["businesses"] + [t[0] for t in TABLES]
            for table in names:
                sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
                if sql:
                    target.execute(sql[0])
            target.execute("CREATE TABLE bundle_meta (key TEXT PRIMARY KEY, value TEXT)")
            counts: dict[str, int] = {}
            rows = [("businesses", [dict(business)])]
            have = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table, where, _ in TABLES:
                if table in have:
                    rows.append((table, [dict(r) for r in connection.execute(f"SELECT * FROM {table} WHERE {where}", (business_id,))]))
            for table, items in rows:
                for item in items:
                    columns = list(item)
                    target.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
                                   [item[c] for c in columns])
                counts[table] = len(items)
            meta = {"format": str(FORMAT), "app": "Ledgerly", "business_name": business["name"],
                    "business_slug": business["slug"], "exported_at": db.utc_now(), "exported_by": exported_by,
                    "counts": json.dumps(counts)}
            target.executemany("INSERT INTO bundle_meta(key, value) VALUES (?, ?)", list(meta.items()))
            target.commit()
        finally:
            target.close()
        data = Path(name).read_bytes()
    finally:
        Path(name).unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(name + suffix).unlink(missing_ok=True)
    return encrypt(data, password) if password else data


def file_name(connection: sqlite3.Connection, business_id: int) -> str:
    from datetime import date
    slug = connection.execute("SELECT slug FROM businesses WHERE id = ?", (business_id,)).fetchone()["slug"]
    return f"{slug}-{date.today():%Y%m%d}.ledgerly"


# ---------- import ----------

@contextmanager
def _open(data: bytes, password: str = "") -> Iterator[sqlite3.Connection]:
    if is_encrypted(data):
        if not password:
            raise NeedPassword()
        data = decrypt(data, password)
    if not data.startswith(SQLITE_MAGIC):
        raise ValueError("This is not a Ledgerly business file.")
    handle, name = tempfile.mkstemp(suffix=".ledgerly")
    os.close(handle)
    Path(name).write_bytes(data)
    source = sqlite3.connect(name)
    source.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "bundle_meta" not in tables or "businesses" not in tables:
            raise ValueError("This is not a Ledgerly business file.")
        yield source
    finally:
        source.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(name + suffix).unlink(missing_ok=True)


def _meta(source: sqlite3.Connection) -> dict[str, Any]:
    meta = {r["key"]: r["value"] for r in source.execute("SELECT key, value FROM bundle_meta")}
    if meta.get("format") != str(FORMAT):
        raise ValueError("This file was made by a newer version of Ledgerly. Update the app first.")
    meta["counts"] = json.loads(meta.get("counts") or "{}")
    return meta


def _existing(connection: sqlite3.Connection, name: str, slug: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM businesses WHERE LOWER(name) = LOWER(?) OR slug = ?", (name, slug)).fetchone()


def preview(connection: sqlite3.Connection, data: bytes, password: str = "") -> dict[str, Any]:
    """What the file holds and what importing it would replace. Raises NeedPassword for an encrypted file."""
    with _open(data, password) as source:
        meta = _meta(source)
        business = source.execute("SELECT * FROM businesses").fetchone()
        existing = _existing(connection, business["name"], business["slug"])
        info: dict[str, Any] = {
            "name": business["name"], "exported_at": meta["exported_at"], "exported_by": meta.get("exported_by", ""),
            "counts": {k: meta["counts"].get(k, 0) for k in COUNTED}, "exists": existing is not None,
            "current": {}, "newer_here": False, "latest_here": None}
        if existing:
            bid = int(existing["id"])
            have = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            info["current"] = {t: connection.execute(f"SELECT COUNT(*) FROM {t} WHERE business_id = ?", (bid,)).fetchone()[0]
                               for t in COUNTED if t in have}
            latest = connection.execute("SELECT MAX(updated_at) FROM transactions WHERE business_id = ?", (bid,)).fetchone()[0]
            info["latest_here"] = latest
            info["newer_here"] = bool(latest and latest > meta["exported_at"])
        return info


def _remap_json(text: str | None, maps: dict[str, dict[int, int]]) -> str | None:
    if not text:
        return text
    try:
        value = json.loads(text)
    except ValueError:
        return text
    keys = {"category_id": "categories", "related_account_id": "accounts", "learned_rule_id": "rules"}

    def fix(item: Any) -> Any:
        if isinstance(item, dict):
            out = {}
            for key, val in item.items():
                out[key] = maps[keys[key]].get(val) if key in keys and isinstance(val, int) else fix(val)
            return out
        if isinstance(item, list):
            return [fix(v) for v in item]
        return item

    return json.dumps(fix(value))


def _wipe(connection: sqlite3.Connection, business_id: int) -> None:
    have = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, where, _ in reversed(TABLES):
        if table in have:
            connection.execute(f"DELETE FROM {table} WHERE {where}", (business_id,))


def apply(connection: sqlite3.Connection, data: bytes, password: str = "") -> dict[str, Any]:
    """Replace (or add) the business from the file. The caller makes a backup first and commits."""
    with _open(data, password) as source:
        meta = _meta(source)
        biz = dict(source.execute("SELECT * FROM businesses").fetchone())
        existing = _existing(connection, biz["name"], biz["slug"])
        if existing:
            business_id = int(existing["id"])
            _wipe(connection, business_id)
            connection.execute("UPDATE businesses SET name = ?, slug = ?, active = ? WHERE id = ?",
                               (biz["name"], biz["slug"], biz["active"], business_id))
        else:
            business_id = int(connection.execute(
                "INSERT INTO businesses(name, slug, active, created_at) VALUES (?, ?, ?, ?)",
                (biz["name"], biz["slug"], biz["active"], biz["created_at"])).lastrowid)
        maps: dict[str, dict[int, int]] = {t[0]: {} for t in TABLES}
        added: dict[str, int] = {}
        for table, _, fks in TABLES:
            target_columns = {r["name"] for r in connection.execute(f"PRAGMA table_info({table})")}
            if not target_columns:
                continue
            try:
                items = source.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                items = []
            for item in items:
                row = {k: item[k] for k in item.keys() if k in target_columns and k != "id"}
                if "business_id" in target_columns:
                    row["business_id"] = business_id
                for column, ref in fks.items():
                    if column in row and row[column] is not None:
                        row[column] = maps[ref].get(int(row[column]))
                if table == "transactions":
                    row["split_parent_id"] = None
                    if not str(row.get("fingerprint", "")).startswith("split:"):
                        row["fingerprint"] = _fresh_fingerprint(connection, row)
                if table == "transaction_split_log":
                    row["before_json"] = _remap_json(row.get("before_json"), maps)
                    row["lines_json"] = _remap_json(row.get("lines_json"), maps)
                columns = list(row)
                cursor = connection.execute(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
                    [row[c] for c in columns])
                maps[table][int(item["id"])] = int(cursor.lastrowid)
            added[table] = len(items)
        if "split_parent_id" in {r["name"] for r in connection.execute("PRAGMA table_info(transactions)")}:
            for item in source.execute("SELECT id, split_parent_id FROM transactions WHERE split_parent_id IS NOT NULL"):
                connection.execute("UPDATE transactions SET split_parent_id = ? WHERE id = ?",
                                   (maps["transactions"].get(int(item["split_parent_id"])), maps["transactions"][int(item["id"])]))
        return {"business_id": business_id, "name": biz["name"], "replaced": existing is not None,
                "added": {k: added.get(k, 0) for k in COUNTED}, "exported_at": meta["exported_at"]}


def _fresh_fingerprint(connection: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Recompute with this database's ids so duplicate detection keeps working; never collide."""
    base = db.transaction_fingerprint(row["business_id"], row["account_id"], row["transaction_date"],
                                      float(row["source_amount"]), row["description"], row.get("source_reference"))
    fingerprint, n = base, 0
    while connection.execute("SELECT 1 FROM transactions WHERE fingerprint = ?", (fingerprint,)).fetchone():
        n += 1
        fingerprint = f"{base}#{n}"
    return fingerprint
