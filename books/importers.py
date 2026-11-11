from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import db


def money(value: Any) -> float:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    if not text:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    amount = float(text)
    return -abs(amount) if negative else amount


def iso_date(value: Any, fallback: str | None = None) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        if fallback:
            return iso_date(fallback)
        raise ValueError("A transaction date is required")
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unsupported date: {text}")


def _reader_after_header(text: str, required: set[str]) -> csv.DictReader:
    lines = text.replace("\ufeff", "").splitlines()
    for index, line in enumerate(lines):
        fields = next(csv.reader([line]))
        if required.issubset({field.strip() for field in fields}):
            return csv.DictReader(lines[index:])
    raise ValueError(f"Could not find columns: {', '.join(sorted(required))}")


def detect_format(text: str) -> str:
    head = "\n".join(text.splitlines()[:15])
    if "CardHolder Name,Account/Card Number" in head:
        return "boa_credit_card"
    if "Date,Description,Amount,Running Bal." in head:
        return "boa_checking"
    if "Posted Date" in head and "Full description" in head:
        return "truist_checking"
    if "Posted Date" in head and ",Description,Amount" in head:
        return "line_of_credit"
    return "generic"


def parse_csv_text(text: str, fmt: str = "auto") -> list[dict[str, Any]]:
    fmt = detect_format(text) if fmt == "auto" else fmt
    rows: list[dict[str, Any]] = []
    if fmt == "boa_checking":
        reader = _reader_after_header(text, {"Date", "Description", "Amount"})
        for index, row in enumerate(reader, start=1):
            if not row.get("Amount"):
                continue
            amount = money(row["Amount"])
            rows.append({"transaction_date": iso_date(row["Date"]), "posting_date": iso_date(row["Date"]),
                         "description": row["Description"].strip(), "source_amount": amount,
                         "source_category": "", "source_reference": str(index), "raw": row})
    elif fmt == "boa_credit_card":
        reader = _reader_after_header(text, {"Posting Date", "Trans. Date", "Description", "Amount"})
        for row in reader:
            if not row.get("Amount"):
                continue
            rows.append({"transaction_date": iso_date(row.get("Trans. Date"), row.get("Posting Date")),
                         "posting_date": iso_date(row.get("Posting Date")),
                         "description": row["Description"].strip(), "source_amount": money(row["Amount"]),
                         "source_category": row.get("Expense Category", ""),
                         "source_reference": row.get("Reference ID", ""), "raw": row})
    elif fmt in {"truist_checking", "line_of_credit"}:
        required = {"Posted Date", "Amount"}
        reader = _reader_after_header(text, required)
        for index, row in enumerate(reader, start=1):
            if not row.get("Amount"):
                continue
            description = row.get("Full description") or row.get("Description") or ""
            rows.append({"transaction_date": iso_date(row.get("Transaction Date"), row.get("Posted Date")),
                         "posting_date": iso_date(row.get("Posted Date")), "description": description.strip(),
                         "source_amount": money(row["Amount"]), "source_category": row.get("Category name", ""),
                         "source_reference": row.get("Check/Serial #") or str(index), "raw": row})
    else:
        reader = csv.DictReader(io.StringIO(text.strip()))
        names = {re.sub(r"[^a-z]", "", name.lower()): name for name in (reader.fieldnames or [])}
        date_col = names.get("date") or names.get("transactiondate") or names.get("posteddate")
        desc_col = names.get("description") or names.get("fulldescription") or names.get("merchant")
        amount_col = names.get("amount")
        if not all((date_col, desc_col, amount_col)):
            raise ValueError("Pasted rows need Date, Description, and Amount columns")
        for index, row in enumerate(reader, start=1):
            if not row.get(amount_col):
                continue
            rows.append({"transaction_date": iso_date(row[date_col]), "posting_date": iso_date(row[date_col]),
                         "description": row[desc_col].strip(), "source_amount": money(row[amount_col]),
                         "source_category": "", "source_reference": str(index), "raw": row})
    return rows


def preview_csv(text: str, account_type: str, fmt: str = "auto") -> list[dict[str, Any]]:
    rows = parse_csv_text(text, fmt)
    for row in rows:
        row["signed_amount"] = -row["source_amount"] if account_type == "credit_card" else row["source_amount"]
    return rows


def commit_rows(connection: sqlite3.Connection, *, business_id: int, account_id: int,
                account_type: str, rows: list[dict[str, Any]], source_name: str,
                source_type: str = "csv") -> dict[str, int]:
    batch_id = db.create_import_batch(connection, business_id, account_id, source_name, source_type)
    imported = duplicates = auto = review = 0
    for row in rows:
        signed = float(row.get("signed_amount", -row["source_amount"] if account_type == "credit_card" else row["source_amount"]))
        _, duplicate, classified = db.insert_transaction(
            connection, business_id=business_id, account_id=account_id,
            transaction_date=row["transaction_date"], posting_date=row.get("posting_date"),
            description=row["description"], source_amount=float(row["source_amount"]), signed_amount=signed,
            source_category=row.get("source_category"), source_file=source_name,
            source_reference=row.get("source_reference"), raw=row.get("raw"), import_batch_id=batch_id,
        )
        if duplicate:
            duplicates += 1
        else:
            imported += 1
            auto += int(classified)
            review += int(not classified)
    db.finish_import_batch(connection, batch_id, imported, duplicates, review)
    return {"batch_id": batch_id, "imported": imported, "duplicates": duplicates,
            "auto_classified": auto, "needs_review": review}


def read_path(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")
