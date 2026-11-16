"""Line-of-credit statements: classify the lines, match them to checking, and book interest as expense.

Sign convention for rows kept on a line-of-credit account is the same cash view used everywhere else:
money borrowed is positive (an advance), money paid out is negative (payment, interest, fee).
A statement line that matches a checking transaction is kept as an "Excluded" mirror so nothing is
counted twice; the checking side carries the loan treatment.
"""
from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime
from typing import Any

from . import db

INTEREST_CATEGORY = "Interest expense"
FEES_CATEGORY = "Bank fees"
LOAN_TREATMENT_FOR = {"advance": "Loan draw", "payment": "Principal repayment"}


def classify_line(description: str) -> str:
    """advance, payment, interest, fee or other, from the words on a statement line."""
    text = (description or "").lower()
    if re.search(r"interest|finance charge", text):
        return "interest"
    if re.search(r"fee|annual|late charge|service charge", text):
        return "fee"
    if re.search(r"payment|pymt|pmt|ach credit|autopay|received|credit", text):
        return "payment"
    if re.search(r"advance|draw|borrow|transfer from|check|disbursement|cash adv|withdraw", text):
        return "advance"
    return "other"


def orient(rows: list[dict[str, Any]], payments_are: str = "auto") -> list[dict[str, Any]]:
    """Add ``kind`` and the cash-view ``signed_amount`` to parsed statement rows.

    ``payments_are`` is "positive", "negative" or "auto" (decided from the lines that say payment).
    """
    kinds = [classify_line(row["description"]) for row in rows]
    if payments_are == "auto":
        votes = [row["source_amount"] > 0 for row, kind in zip(rows, kinds) if kind == "payment"]
        payments_are = "positive" if votes and sum(votes) * 2 >= len(votes) else "negative"
    out = []
    for row, kind in zip(rows, kinds):
        amount = abs(float(row["source_amount"]))
        if kind == "other":
            is_payment = (float(row["source_amount"]) > 0) == (payments_are == "positive")
            kind = "payment" if is_payment else "advance"
        signed = amount if kind == "advance" else -amount
        out.append({**row, "kind": kind, "signed_amount": round(signed, 2)})
    return out


def parse_pdf_text(text: str) -> list[dict[str, Any]]:
    """Best effort: lines that start with a date and end with an amount."""
    year = None
    years = re.findall(r"\b(20\d{2})\b", text)
    if years:
        year = max(set(years), key=years.count)
    rows = []
    for index, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(.*?)\s+(-?\(?\$?[\d,]+\.\d{2}\)?-?)\s*$", line)
        if not match:
            continue
        date_text, description, amount_text = match.groups()
        if date_text.count("/") == 1:
            date_text = f"{date_text}/{year or datetime.now().year}"
        try:
            date = datetime.strptime(date_text, "%m/%d/%Y" if len(date_text.split("/")[-1]) == 4 else "%m/%d/%y")
        except ValueError:
            continue
        negative = amount_text.startswith("-") or amount_text.endswith("-") or "(" in amount_text
        amount = float(re.sub(r"[^\d.]", "", amount_text))
        rows.append({"transaction_date": date.date().isoformat(), "posting_date": date.date().isoformat(),
                     "description": description.strip(), "source_amount": -amount if negative else amount,
                     "source_category": "", "source_reference": str(index), "raw": {"line": line.strip()}})
    return rows


def parse_pdf(data: bytes) -> list[dict[str, Any]]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return parse_pdf_text("\n".join(page.extract_text() or "" for page in reader.pages))


def import_rows(connection: sqlite3.Connection, *, business_id: int, account_id: int, rows: list[dict[str, Any]],
                source_name: str) -> dict[str, int]:
    """Save oriented statement rows already classified: interest and fees as expense, advances and payments as loan money."""
    account = connection.execute("SELECT name FROM accounts WHERE id = ?", (account_id,)).fetchone()
    batch_id = db.create_import_batch(connection, business_id, account_id, source_name, "loc")
    interest_id = db.get_or_create_category(connection, business_id, INTEREST_CATEGORY, "Expense")
    fees_id = db.get_or_create_category(connection, business_id, FEES_CATEGORY, "Expense")
    imported = duplicates = 0
    for row in rows:
        kind = row["kind"]
        treatment = {"interest": "Expense", "fee": "Expense"}.get(kind, LOAN_TREATMENT_FOR.get(kind, "Needs review"))
        category_id = {"interest": interest_id, "fee": fees_id}.get(kind)
        txn_id, duplicate, _ = db.insert_transaction(
            connection, business_id=business_id, account_id=account_id, transaction_date=row["transaction_date"],
            posting_date=row.get("posting_date"), description=row["description"],
            source_amount=float(row["source_amount"]), signed_amount=float(row["signed_amount"]),
            source_category=kind, category_id=category_id, treatment=treatment,
            status="confirmed" if treatment != "Needs review" else "needs_review",
            source_file=source_name, source_reference=row.get("source_reference"), raw=row.get("raw"),
            import_batch_id=batch_id, allow_rules=False)
        if duplicate:
            duplicates += 1
            continue
        imported += 1
        if kind in {"advance", "payment"} and account:
            connection.execute("UPDATE transactions SET counterparty = ? WHERE id = ?", (account["name"], txn_id))
    db.finish_import_batch(connection, batch_id, imported, duplicates, 0)
    return {"batch_id": batch_id, "imported": imported, "duplicates": duplicates}


def _candidates_on_loc(connection: sqlite3.Connection, business_id: int, loc_account_id: int | None):
    clause = "AND t.account_id = ?" if loc_account_id else ""
    params: list[Any] = [business_id] + ([loc_account_id] if loc_account_id else [])
    return connection.execute(
        f"""SELECT t.* FROM transactions t JOIN accounts a ON a.id = t.account_id
            WHERE t.business_id = ? AND a.account_type = 'line_of_credit' AND t.split_parent_id IS NULL
              AND t.status != 'split' {clause}
            ORDER BY t.transaction_date, t.id""", params).fetchall()


def plan(connection: sqlite3.Connection, business_id: int, loc_account_id: int | None = None,
         window_days: int = 5) -> list[dict[str, Any]]:
    """Match statement advances and payments to checking transactions of the same amount, and allocate interest.

    Returns one dict per match: the LOC row, the checking row, the interest paid within the payment
    (to be booked as expense) and the principal that remains.
    """
    loc_rows = _candidates_on_loc(connection, business_id, loc_account_id)
    movement = [r for r in loc_rows if r["treatment"] in ("Loan draw", "Principal repayment")
                and r["related_account_id"] is None]
    interest = [r for r in loc_rows if r["treatment"] == "Expense" and r["source_category"] == "interest"]
    checking = connection.execute(
        """SELECT t.* FROM transactions t JOIN accounts a ON a.id = t.account_id
           WHERE t.business_id = ? AND a.account_type IN ('checking', 'savings') AND t.split_parent_id IS NULL
             AND t.status != 'split' AND t.treatment IN ('Needs review', 'Loan draw', 'Principal repayment', 'Transfer')
             AND (t.related_account_id IS NULL OR t.related_account_id IN
                  (SELECT id FROM accounts WHERE account_type = 'line_of_credit'))
             AND COALESCE(t.notes, '') NOT LIKE 'Matched to %'
           ORDER BY t.transaction_date, t.id""", (business_id,)).fetchall()
    taken: set[int] = set()
    matches: list[dict[str, Any]] = []
    for loc in movement:
        best = None
        for bank in checking:
            if bank["id"] in taken or abs(float(bank["signed_amount"]) - float(loc["signed_amount"])) > 0.005:
                continue
            gap = abs((datetime.fromisoformat(bank["transaction_date"]) - datetime.fromisoformat(loc["transaction_date"])).days)
            if gap <= window_days and (best is None or gap < best[0]):
                best = (gap, bank)
        if best:
            taken.add(best[1]["id"])
            matches.append({"loc": dict(loc), "bank": dict(best[1]), "interest": 0.0, "interest_rows": []})
    # interest charged on the statement is part of the payment that follows it
    used: set[int] = set()
    for match in sorted(matches, key=lambda m: m["loc"]["transaction_date"]):
        if match["loc"]["treatment"] != "Principal repayment":
            continue
        remaining = abs(float(match["loc"]["signed_amount"]))
        for row in interest:
            if row["id"] in used or row["account_id"] != match["loc"]["account_id"]:
                continue
            charge = abs(float(row["signed_amount"]))
            gap = (datetime.fromisoformat(match["loc"]["transaction_date"]) - datetime.fromisoformat(row["transaction_date"])).days
            if -window_days <= gap <= 45 and charge <= remaining + 0.005:
                used.add(row["id"])
                match["interest"] = round(match["interest"] + charge, 2)
                match["interest_rows"].append(dict(row))
                remaining -= charge
    return matches


def apply(connection: sqlite3.Connection, business_id: int, matches: list[dict[str, Any]]) -> dict[str, int]:
    """Carry out the plan: loan treatment on the checking side, interest booked as expense, LOC lines mirrored."""
    now = db.utc_now()
    interest_cat = db.get_or_create_category(connection, business_id, INTEREST_CATEGORY, "Expense")
    result = {"matched": 0, "interest_expensed": 0, "split": 0}
    for match in matches:
        loc, bank, interest = match["loc"], match["bank"], match["interest"]
        loc_name = connection.execute("SELECT name FROM accounts WHERE id = ?", (loc["account_id"],)).fetchone()["name"]
        treatment = loan = loc["treatment"]
        note = f"Matched to {loc_name} statement line {loc['transaction_date']} ${abs(float(loc['signed_amount'])):,.2f}"
        total = abs(float(bank["signed_amount"]))
        counterparty = (bank["counterparty"] or "").strip() or loc_name
        if interest > 0.004 and treatment == "Principal repayment":
            principal = round(total - interest, 2)
            lines = [{"amount": interest, "category_id": interest_cat, "treatment": "Expense",
                      "counterparty": loc_name, "notes": note + " · interest"}]
            if principal > 0.004:
                lines.insert(0, {"amount": principal, "category_id": None, "treatment": "Principal repayment",
                                 "related_account_id": loc["account_id"], "counterparty": counterparty,
                                 "notes": note + " · principal"})
                db.split_transaction(connection, business_id=business_id, transaction_id=bank["id"], lines=lines)
                result["split"] += 1
            else:
                connection.execute(
                    """UPDATE transactions SET treatment = 'Expense', category_id = ?, related_account_id = NULL,
                       counterparty = ?, status = 'confirmed', notes = ?, reviewed_at = ?, updated_at = ? WHERE id = ?""",
                    (interest_cat, loc_name, note + " · interest", now, now, bank["id"]))
            result["interest_expensed"] += 1
            for row in match["interest_rows"]:
                connection.execute(
                    """UPDATE transactions SET treatment = 'Excluded', category_id = NULL, status = 'confirmed',
                       notes = ?, updated_at = ? WHERE id = ?""",
                    (f"Interest paid with checking transaction #{bank['id']} (booked there as expense)", now, row["id"]))
        else:
            connection.execute(
                """UPDATE transactions SET treatment = ?, related_account_id = ?, counterparty = ?, status = 'confirmed',
                   notes = ?, reviewed_at = ?, updated_at = ? WHERE id = ?""",
                (loan, loc["account_id"], counterparty, note, now, now, bank["id"]))
        connection.execute(
            """UPDATE transactions SET treatment = 'Excluded', related_account_id = ?, status = 'confirmed',
               counterparty = NULL, notes = ?, updated_at = ? WHERE id = ?""",
            (bank["account_id"], f"Matched to checking transaction #{bank['id']} ({loan})", now, loc["id"]))
        result["matched"] += 1
    return result


def reconcile(connection: sqlite3.Connection, business_id: int, loc_account_id: int | None = None) -> dict[str, Any]:
    matches = plan(connection, business_id, loc_account_id)
    outcome = apply(connection, business_id, matches)
    outcome["matches"] = matches
    return outcome
