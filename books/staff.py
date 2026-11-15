"""Simple staff payments by month and revenue picked from companies.

Two plain lists: what was paid to each staff member or staff company in a month, and which bank deposits
count as revenue from a company. Nothing is computed from rates or hours; you enter or pick the amounts.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    match_names TEXT NOT NULL DEFAULT '',
    default_client TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(business_id, name)
);

CREATE TABLE IF NOT EXISTS staff_payments (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revenue_picks (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    company TEXT NOT NULL,
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
"""

NOT_REVENUE = ("Transfer", "Owner contribution", "Loan draw", "Receivable repayment")


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def clean_month(value: str) -> str:
    text = (value or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise ValueError("Month must look like 2026-03.")
    return text


def month_range(month: str) -> tuple[str, str]:
    year, number = int(month[:4]), int(month[5:])
    start = date(year, number, 1)
    end = date(year + (number == 12), number % 12 + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def recent_months(count: int = 24, today: date | None = None) -> list[str]:
    """Newest first, starting with next month."""
    today = today or date.today()
    year, number = today.year, today.month + 1
    months = []
    for _ in range(count):
        if number > 12:
            year, number = year + 1, 1
        months.append(f"{year:04d}-{number:02d}")
        number -= 1
        if number == 0:
            year, number = year - 1, 12
    return months


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (value or "").lower()).split())


def memo_text(row: Any) -> str:
    """Everything a person wrote about a transaction: the note, the name filed on it, and check payee/memo."""
    parts = []
    for label, value in (("Note", row["notes"]), ("Name", row["counterparty"]), ("Check", row["check_text"])):
        text = " ".join(str(value or "").split())
        if text:
            parts.append(f"{label}: {text}" if label != "Note" else text)
    return " · ".join(parts)


def _text_hit(name: str, haystack: str) -> bool:
    key = _normalize(name)
    if len(key) >= 3 and key in haystack:
        return True
    parts = key.split()
    return len(parts) >= 2 and all(re.search(rf"\b{re.escape(p)}\b", haystack) for p in (parts[0], parts[-1]))


# ---------------------------------------------------------------- staff paid by month

def list_staff(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [dict(r) for r in connection.execute(
        "SELECT * FROM staff WHERE business_id = ? ORDER BY name COLLATE NOCASE", (business_id,))]


def get_or_create_staff(connection: sqlite3.Connection, business_id: int, name: str) -> int:
    clean = " ".join((name or "").split())
    if not clean:
        raise ValueError("Pick or type a staff member or company.")
    row = connection.execute("SELECT id FROM staff WHERE business_id = ? AND LOWER(name) = LOWER(?)",
                             (business_id, clean)).fetchone()
    if row:
        return int(row["id"])
    return int(connection.execute(
        "INSERT INTO staff(business_id, name, created_at) VALUES (?, ?, ?)", (business_id, clean, db.utc_now())).lastrowid)


def add_payment(connection: sqlite3.Connection, business_id: int, *, name: str, month: str, amount: float,
                note: str = "") -> int:
    month = clean_month(month)
    if amount is None or float(amount) <= 0:
        raise ValueError("Enter the amount paid.")
    staff_id = get_or_create_staff(connection, business_id, name)
    return int(connection.execute(
        "INSERT INTO staff_payments(business_id, staff_id, month, amount, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (business_id, staff_id, month, round(float(amount), 2), (note or "").strip(), db.utc_now())).lastrowid)


def list_payments(connection: sqlite3.Connection, business_id: int, month: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connection.execute(
        """SELECT p.id, p.staff_id, s.name AS staff, p.month, p.amount, p.note, p.transaction_id,
                  t.transaction_date AS bank_date, t.description AS bank_description
             FROM staff_payments p JOIN staff s ON s.id = p.staff_id
             LEFT JOIN transactions t ON t.id = p.transaction_id
            WHERE p.business_id = ? AND p.month = ? ORDER BY s.name COLLATE NOCASE, p.id""", (business_id, month))]


def delete_payment(connection: sqlite3.Connection, business_id: int, payment_id: int) -> None:
    connection.execute("DELETE FROM staff_payments WHERE id = ? AND business_id = ?", (payment_id, business_id))


def paid_by_month(connection: sqlite3.Connection, business_id: int) -> dict[str, float]:
    return {r["month"]: round(float(r["total"]), 2) for r in connection.execute(
        "SELECT month, SUM(amount) AS total FROM staff_payments WHERE business_id = ? GROUP BY month", (business_id,))}


def payment_suggestions(connection: sqlite3.Connection, business_id: int, month: str, window_days: int = 20) -> list[dict[str, Any]]:
    """Bank payments that look like an unmatched staff payment: the amount equals it, or the name is in the memo."""
    month = clean_month(month)
    start, end = month_range(month)
    start = (date.fromisoformat(start) - timedelta(days=window_days // 2)).isoformat()
    end = (date.fromisoformat(end) + timedelta(days=window_days)).isoformat()
    open_payments = [p for p in list_payments(connection, business_id, month) if not p["transaction_id"]]
    if not open_payments:
        return []
    used = {int(r["transaction_id"]) for r in connection.execute(
        "SELECT transaction_id FROM staff_payments WHERE business_id = ? AND transaction_id IS NOT NULL", (business_id,))}
    txns = connection.execute(
        """SELECT t.id, t.transaction_date, t.description, t.signed_amount, t.counterparty, t.status,
                  (SELECT GROUP_CONCAT(COALESCE(r.payee, '') || ' ' || COALESCE(r.memo, ''), ' ')
                     FROM check_register r WHERE r.transaction_id = t.id) AS check_text
             FROM transactions t
            WHERE t.business_id = ? AND t.signed_amount < 0 AND t.status <> 'split'
              AND t.treatment NOT IN ('Transfer', 'Owner draw', 'Principal repayment', 'Loan receivable')
              AND t.transaction_date BETWEEN ? AND ?""", (business_id, start, end)).fetchall()
    found = []
    for payment in open_payments:
        for txn in txns:
            if int(txn["id"]) in used:
                continue
            haystack = _normalize(" ".join([txn["description"] or "", txn["counterparty"] or "", txn["check_text"] or ""]))
            same_amount = abs(abs(float(txn["signed_amount"])) - payment["amount"]) < 0.01
            named = _text_hit(payment["staff"], haystack)
            if not (same_amount or named):
                continue
            found.append({"payment": payment, "transaction": dict(txn),
                          "score": (4 if same_amount else 0) + (3 if named else 0),
                          "why": ("same amount and name in the memo" if same_amount and named else
                                  "same amount" if same_amount else "name in the memo, different amount")})
    found.sort(key=lambda s: (-s["score"], s["transaction"]["transaction_date"]))
    return found


def copy_payments(connection: sqlite3.Connection, business_id: int, source: str, target: str) -> int:
    """Copy one month's payments (names, amounts, notes) to another month. Bank links are not copied."""
    source, target = clean_month(source), clean_month(target)
    if source == target:
        raise ValueError("Choose a different month to copy to.")
    existing = {(r["staff_id"], round(float(r["amount"]), 2), r["note"]) for r in connection.execute(
        "SELECT staff_id, amount, note FROM staff_payments WHERE business_id = ? AND month = ?", (business_id, target))}
    copied = 0
    for row in connection.execute(
            "SELECT staff_id, amount, note FROM staff_payments WHERE business_id = ? AND month = ?", (business_id, source)).fetchall():
        key = (row["staff_id"], round(float(row["amount"]), 2), row["note"])
        if key in existing:
            continue
        connection.execute(
            "INSERT INTO staff_payments(business_id, staff_id, month, amount, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (business_id, row["staff_id"], target, row["amount"], row["note"], db.utc_now()))
        copied += 1
    return copied


def name_matches(connection: sqlite3.Connection, business_id: int, name: str, month: str) -> list[dict[str, Any]]:
    """Money-out bank transactions in the month that mention this name (description, payee, check payee or saved names)."""
    month = clean_month(month)
    clean = " ".join((name or "").split())
    if not clean:
        return []
    start, end = month_range(month)
    names = [clean]
    known = connection.execute("SELECT match_names FROM staff WHERE business_id = ? AND LOWER(name) = LOWER(?)",
                               (business_id, clean)).fetchone()
    if known and known["match_names"]:
        names += [part for part in re.split(r"[\n,;]+", known["match_names"]) if part.strip()]
    used = {int(r["transaction_id"]) for r in connection.execute(
        "SELECT transaction_id FROM staff_payments WHERE business_id = ? AND transaction_id IS NOT NULL", (business_id,))}
    found = []
    for txn in connection.execute(
            """SELECT t.id, t.transaction_date, t.description, t.signed_amount, t.counterparty, t.treatment, t.notes,
                      c.name AS category,
                      (SELECT GROUP_CONCAT(COALESCE(r.payee, '') || ' ' || COALESCE(r.memo, ''), ' ')
                         FROM check_register r WHERE r.transaction_id = t.id) AS check_text
                 FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
                WHERE t.business_id = ? AND t.signed_amount < 0 AND t.status <> 'split'
                  AND t.treatment NOT IN ('Transfer', 'Owner draw', 'Principal repayment', 'Loan receivable')
                  AND t.transaction_date BETWEEN ? AND ?
                ORDER BY t.transaction_date, t.id""", (business_id, start, end)):
        if int(txn["id"]) in used:
            continue
        haystack = _normalize(" ".join([txn["description"] or "", txn["counterparty"] or "", txn["check_text"] or ""]))
        if any(_text_hit(n, haystack) for n in names):
            item = dict(txn)
            item["memo"] = memo_text(txn)
            found.append(item)
    return found


def add_payments_from_transactions(connection: sqlite3.Connection, business_id: int, *, name: str, month: str,
                                   transaction_ids: list[int]) -> int:
    """One payment per chosen bank transaction, with the bank amount, linked to it."""
    month = clean_month(month)
    added = 0
    for transaction_id in transaction_ids:
        txn = connection.execute(
            "SELECT * FROM transactions WHERE id = ? AND business_id = ? AND signed_amount < 0", (transaction_id, business_id)).fetchone()
        if txn is None:
            raise ValueError("Transaction not found.")
        if connection.execute("SELECT 1 FROM staff_payments WHERE transaction_id = ?", (transaction_id,)).fetchone():
            continue
        payment_id = add_payment(connection, business_id, name=name, month=month, amount=abs(float(txn["signed_amount"])),
                                 note=(txn["description"] or "")[:60])
        connection.execute("UPDATE staff_payments SET transaction_id = ? WHERE id = ?", (transaction_id, payment_id))
        added += 1
    return added


def link_payment(connection: sqlite3.Connection, business_id: int, payment_id: int, transaction_id: int,
                 *, category_id: int | None = None) -> None:
    """Tie a staff payment to the bank payment. With a category, also file the bank transaction as that expense."""
    payment = connection.execute(
        "SELECT p.*, s.name AS staff FROM staff_payments p JOIN staff s ON s.id = p.staff_id "
        "WHERE p.id = ? AND p.business_id = ?", (payment_id, business_id)).fetchone()
    txn = connection.execute("SELECT * FROM transactions WHERE id = ? AND business_id = ?",
                             (transaction_id, business_id)).fetchone()
    if payment is None or txn is None:
        raise ValueError("Payment or transaction not found.")
    if abs(abs(float(txn["signed_amount"])) - float(payment["amount"])) >= 0.01:
        raise ValueError(f"The bank amount is ${abs(float(txn['signed_amount'])):,.2f}, not ${payment['amount']:,.2f}. "
                         "Fix the amount first.")
    if connection.execute("SELECT 1 FROM staff_payments WHERE transaction_id = ? AND id <> ?",
                          (transaction_id, payment_id)).fetchone():
        raise ValueError("That bank payment is already linked to another staff payment.")
    if category_id:
        db.update_transaction_classification(connection, transaction_id, category_id=category_id, treatment="Expense")
        db.set_transaction_counterparty(connection, business_id=business_id, transaction_id=transaction_id,
                                        counterparty=payment["staff"])
    connection.execute("UPDATE staff_payments SET transaction_id = ? WHERE id = ?", (transaction_id, payment_id))


def unlink_payment(connection: sqlite3.Connection, business_id: int, payment_id: int) -> None:
    connection.execute("UPDATE staff_payments SET transaction_id = NULL WHERE id = ? AND business_id = ?",
                       (payment_id, business_id))


# ---------------------------------------------------------------- revenue from a company

def revenue_candidates(connection: sqlite3.Connection, business_id: int, company: str, start: str, end: str) -> list[dict[str, Any]]:
    """Deposits whose description, name or check payee mentions the company. Marks the ones already picked."""
    key = " ".join((company or "").split())
    if not key:
        return []
    rows = []
    for row in connection.execute(
            """SELECT t.id, t.transaction_date, t.description, t.signed_amount, t.counterparty, t.treatment, t.notes,
                      c.name AS category, rp.company AS picked_company,
                      (SELECT GROUP_CONCAT(COALESCE(r.payee, '') || ' ' || COALESCE(r.memo, ''), ' ')
                         FROM check_register r WHERE r.transaction_id = t.id) AS check_text
                 FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
                 LEFT JOIN revenue_picks rp ON rp.transaction_id = t.id
                WHERE t.business_id = ? AND t.signed_amount > 0 AND t.status <> 'split'
                  AND t.transaction_date BETWEEN ? AND ?
                  AND t.treatment NOT IN ('Transfer', 'Owner contribution', 'Loan draw', 'Receivable repayment')
                ORDER BY t.transaction_date, t.id""", (business_id, start, end)):
        haystack = _normalize(" ".join([row["description"] or "", row["counterparty"] or "", row["check_text"] or ""]))
        if _normalize(key) in haystack and (not row["picked_company"] or row["picked_company"].lower() == key.lower()):
            item = dict(row)
            item["memo"] = memo_text(row)
            item["picked"] = bool(row["picked_company"])
            rows.append(item)
    return rows


def save_revenue_picks(connection: sqlite3.Connection, business_id: int, company: str, shown_ids: list[int],
                       picked_ids: list[int]) -> int:
    """Among the shown deposits, keep exactly the picked ones tagged to this company."""
    name = " ".join((company or "").split())
    if not name:
        raise ValueError("Choose a company.")
    for transaction_id in shown_ids:
        if transaction_id in picked_ids:
            connection.execute(
                """INSERT INTO revenue_picks(business_id, company, transaction_id, created_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(transaction_id) DO UPDATE SET company = excluded.company""",
                (business_id, name, transaction_id, db.utc_now()))
        else:
            connection.execute("DELETE FROM revenue_picks WHERE business_id = ? AND transaction_id = ? AND LOWER(company) = LOWER(?)",
                               (business_id, transaction_id, name))
    return len(picked_ids)


def picked_companies(connection: sqlite3.Connection, business_id: int) -> list[str]:
    return [r["company"] for r in connection.execute(
        "SELECT DISTINCT company FROM revenue_picks WHERE business_id = ? ORDER BY company COLLATE NOCASE", (business_id,))]


def revenue_by_month(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [dict(r) for r in connection.execute(
        """SELECT rp.company, SUBSTR(t.transaction_date, 1, 7) AS month, SUM(t.signed_amount) AS total, COUNT(*) AS deposits
             FROM revenue_picks rp JOIN transactions t ON t.id = rp.transaction_id
            WHERE rp.business_id = ? GROUP BY rp.company, month ORDER BY month DESC, rp.company COLLATE NOCASE""", (business_id,))]


def summary(connection: sqlite3.Connection, business_id: int, months: list[str]) -> list[dict[str, Any]]:
    paid = paid_by_month(connection, business_id)
    revenue: dict[str, float] = {}
    for row in revenue_by_month(connection, business_id):
        revenue[row["month"]] = revenue.get(row["month"], 0.0) + float(row["total"])
    return [{"month": m, "paid": paid.get(m, 0.0), "revenue": round(revenue.get(m, 0.0), 2),
             "margin": round(revenue.get(m, 0.0) - paid.get(m, 0.0), 2)} for m in months]


def previous_month(month: str) -> str:
    month = clean_month(month)
    year, number = int(month[:4]), int(month[5:])
    return f"{year - (number == 1):04d}-{(number - 2) % 12 + 1:02d}"


def autofill_payments(connection: sqlite3.Connection, business_id: int, month: str) -> dict[str, Any]:
    """For everyone paid last month, look for their bank payments this month and add them (linked)."""
    month = clean_month(month)
    people = connection.execute(
        """SELECT DISTINCT s.name FROM staff_payments p JOIN staff s ON s.id = p.staff_id
            WHERE p.business_id = ? AND p.month = ? ORDER BY s.name COLLATE NOCASE""",
        (business_id, previous_month(month))).fetchall()
    added, missing = 0, []
    for person in people:
        found = name_matches(connection, business_id, person["name"], month)
        if found:
            added += add_payments_from_transactions(connection, business_id, name=person["name"], month=month,
                                                    transaction_ids=[t["id"] for t in found])
        else:
            missing.append(person["name"])
    return {"added": added, "people": len(people), "no_match": missing}


def autofill_revenue(connection: sqlite3.Connection, business_id: int, month: str) -> dict[str, Any]:
    """For each company picked last month, pick its matching deposits this month."""
    month = clean_month(month)
    last = previous_month(month)
    companies = [r["company"] for r in connection.execute(
        """SELECT DISTINCT rp.company FROM revenue_picks rp JOIN transactions t ON t.id = rp.transaction_id
            WHERE rp.business_id = ? AND SUBSTR(t.transaction_date, 1, 7) = ? ORDER BY rp.company COLLATE NOCASE""",
        (business_id, last))]
    start, end = month_range(month)
    added, missing = 0, []
    for company in companies:
        fresh = [t["id"] for t in revenue_candidates(connection, business_id, company, start, end) if not t["picked"]]
        if fresh:
            save_revenue_picks(connection, business_id, company, fresh, fresh)
            added += len(fresh)
        else:
            missing.append(company)
    return {"added": added, "companies": len(companies), "no_match": missing}


def months_between(start: str, end: str) -> list[str]:
    """Months from start to end inclusive, oldest first."""
    start, end = clean_month(start), clean_month(end)
    if start > end:
        raise ValueError("The start month is after the end month.")
    months = []
    year, number = int(start[:4]), int(start[5:])
    while f"{year:04d}-{number:02d}" <= end:
        months.append(f"{year:04d}-{number:02d}")
        year, number = year + (number == 12), number % 12 + 1
    return months


def paid_detail(connection: sqlite3.Connection, business_id: int, start: str, end: str,
                names: list[str] | None = None) -> list[dict[str, Any]]:
    """Total paid per person and month in the range, optionally only for the named people."""
    months = months_between(start, end)
    wanted = {n.lower() for n in names or []}
    return [dict(r) for r in connection.execute(
        """SELECT s.name AS name, p.month AS month, SUM(p.amount) AS total FROM staff_payments p
             JOIN staff s ON s.id = p.staff_id
            WHERE p.business_id = ? AND p.month BETWEEN ? AND ? GROUP BY s.name, p.month
            ORDER BY s.name COLLATE NOCASE, p.month""", (business_id, months[0], months[-1]))
        if not wanted or r["name"].lower() in wanted]


def revenue_detail(connection: sqlite3.Connection, business_id: int, start: str, end: str,
                   companies: list[str] | None = None) -> list[dict[str, Any]]:
    """Revenue picked per company and month in the range, optionally only for the named companies."""
    months = months_between(start, end)
    wanted = {c.lower() for c in companies or []}
    return [dict(r) for r in connection.execute(
        """SELECT rp.company AS name, SUBSTR(t.transaction_date, 1, 7) AS month, SUM(t.signed_amount) AS total
             FROM revenue_picks rp JOIN transactions t ON t.id = rp.transaction_id
            WHERE rp.business_id = ? AND SUBSTR(t.transaction_date, 1, 7) BETWEEN ? AND ?
            GROUP BY rp.company, month ORDER BY rp.company COLLATE NOCASE, month""", (business_id, months[0], months[-1]))
        if not wanted or r["name"].lower() in wanted]
