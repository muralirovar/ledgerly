"""Mileage log for tax: business, medical and charity miles with a per-year rate."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS mileage_log (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    trip_date TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    start_place TEXT NOT NULL DEFAULT '',
    end_place TEXT NOT NULL DEFAULT '',
    miles REAL NOT NULL,
    kind TEXT NOT NULL DEFAULT 'Business',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mileage_business_date ON mileage_log(business_id, trip_date);
"""

KINDS = ("Business", "Medical", "Charity", "Personal")
# IRS standard mileage rates for 2025 (dollars per mile); change them on the page when the IRS publishes new ones.
DEFAULT_RATES = {"Business": 0.70, "Medical": 0.21, "Charity": 0.14, "Personal": 0.0}


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _setting_key(year: int, kind: str) -> str:
    return f"mileage_rate_{year}_{kind}"


def get_rates(connection: sqlite3.Connection, year: int) -> dict[str, float]:
    from . import db
    return {kind: float(db.get_setting(connection, _setting_key(year, kind), str(DEFAULT_RATES[kind])))
            for kind in KINDS}


def set_rate(connection: sqlite3.Connection, year: int, kind: str, rate: float) -> None:
    from . import db
    if kind not in KINDS or rate < 0:
        raise ValueError("Unknown mileage type or negative rate.")
    db.set_setting(connection, _setting_key(year, kind), str(rate))


def add_trip(connection: sqlite3.Connection, business_id: int, *, trip_date: str, miles: float, kind: str = "Business",
             purpose: str = "", start_place: str = "", end_place: str = "", notes: str = "") -> int:
    datetime.strptime(trip_date, "%Y-%m-%d")
    if miles <= 0:
        raise ValueError("Miles must be more than zero.")
    if kind not in KINDS:
        raise ValueError("Unknown mileage type.")
    cursor = connection.execute(
        "INSERT INTO mileage_log(business_id, trip_date, purpose, start_place, end_place, miles, kind, notes, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (business_id, trip_date, purpose.strip(), start_place.strip(), end_place.strip(), round(miles, 1), kind,
         notes.strip(), datetime.now().isoformat(timespec="seconds")))
    return int(cursor.lastrowid)


def list_trips(connection: sqlite3.Connection, business_id: int, year: int) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(
        "SELECT * FROM mileage_log WHERE business_id = ? AND trip_date BETWEEN ? AND ? ORDER BY trip_date DESC, id DESC",
        (business_id, f"{year}-01-01", f"{year}-12-31"))]


def delete_trips(connection: sqlite3.Connection, business_id: int, ids: list[int]) -> int:
    count = 0
    for trip_id in ids:
        count += connection.execute("DELETE FROM mileage_log WHERE id = ? AND business_id = ?",
                                    (int(trip_id), business_id)).rowcount
    return count


def summarize(trips: list[dict[str, Any]], rates: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for kind in KINDS:
        miles = round(sum(trip["miles"] for trip in trips if trip["kind"] == kind), 1)
        count = sum(1 for trip in trips if trip["kind"] == kind)
        rows.append({"Type": kind, "Trips": count, "Miles": miles, "Rate per mile": rates[kind],
                     "Deduction": round(miles * rates[kind], 2)})
    return rows
