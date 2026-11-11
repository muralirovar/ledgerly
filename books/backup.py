"""Database backup and restore for the SQLite books file.

Backups use SQLite's online backup API, so they are consistent even while the app is
running. They are stored next to the database in a ``backups`` folder, which lives on the
mounted data volume and therefore survives container rebuilds.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_TABLES = {"businesses", "accounts", "transactions", "categories"}
AUTO_KEEP = 14
_NAME = re.compile(r"^books-\d{8}-\d{6}-[a-z-]+\.db$")


def backup_dir(db_path: str | Path) -> Path:
    path = Path(db_path).parent / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _copy(source: sqlite3.Connection, destination: Path) -> None:
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()


def create_backup(db_path: str | Path, label: str = "manual") -> Path:
    """Write a consistent snapshot of the live database and return its path."""
    label = re.sub(r"[^a-z-]", "", label.lower()) or "manual"
    folder = backup_dir(db_path)
    moment = datetime.now()
    final = folder / f"books-{moment:%Y%m%d-%H%M%S}-{label}.db"
    while final.exists():  # two backups in the same second: nudge the timestamp
        moment += timedelta(seconds=1)
        final = folder / f"books-{moment:%Y%m%d-%H%M%S}-{label}.db"
    temp = final.with_suffix(".partial")
    source = sqlite3.connect(db_path)
    try:
        _copy(source, temp)
    finally:
        source.close()
    temp.replace(final)
    return final


def list_backups(db_path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for item in backup_dir(db_path).glob("books-*.db"):
        if not _NAME.match(item.name):
            continue
        info = item.stat()
        rows.append({
            "name": item.name,
            "kind": item.stem.split("-", 3)[3],
            "created": datetime.fromtimestamp(info.st_mtime),
            "size": info.st_size,
        })
    return sorted(rows, key=lambda row: row["name"], reverse=True)


def backup_path(db_path: str | Path, name: str) -> Path:
    if not _NAME.match(name):
        raise ValueError("Not a recognised backup file name.")
    path = backup_dir(db_path) / name
    if not path.is_file():
        raise ValueError("That backup no longer exists.")
    return path


def validate_backup(path: str | Path) -> dict[str, int]:
    """Check a file is an intact Ledgerly database; return row counts."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"Could not open the file as a database: {exc}") from exc
    try:
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("The database file failed its integrity check.")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as exc:
            raise ValueError("That file is not a valid SQLite database.") from exc
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValueError("That file is not a Ledgerly database (missing: " + ", ".join(sorted(missing)) + ").")
        return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("businesses", "accounts", "transactions")}
    finally:
        connection.close()


def restore_backup(db_path: str | Path, source: str | Path) -> Path:
    """Replace the live database with ``source``, keeping a safety copy of what was there."""
    validate_backup(source)
    safety = create_backup(db_path, "pre-restore")
    origin = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target = sqlite3.connect(db_path)
    try:
        origin.backup(target)
    finally:
        target.close()
        origin.close()
    return safety


def delete_backup(db_path: str | Path, name: str) -> None:
    backup_path(db_path, name).unlink()


def prune_auto_backups(db_path: str | Path, keep: int = AUTO_KEEP) -> int:
    old = [row for row in list_backups(db_path) if row["kind"] == "auto"][keep:]
    for row in old:
        delete_backup(db_path, row["name"])
    return len(old)


def maybe_daily_backup(db_path: str | Path, every_hours: int = 24) -> Path | None:
    """Create an automatic backup if none was made recently. Returns the new path or None."""
    if not Path(db_path).exists():
        return None
    recent = [row for row in list_backups(db_path) if row["kind"] == "auto"]
    if recent and datetime.now() - recent[0]["created"] < timedelta(hours=every_hours):
        return None
    created = create_backup(db_path, "auto")
    prune_auto_backups(db_path)
    return created
