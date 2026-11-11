from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from . import db


def _date(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _rows(path: Path, sheet: str):
    workbook = load_workbook(path, data_only=True, read_only=True)
    iterator = workbook[sheet].iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(iterator)]
    for values in iterator:
        yield dict(zip(headers, values))


def seed_hccl(connection, workbook_path: Path) -> dict[str, int]:
    business_id = db.get_or_create_business(connection, "HCCL")
    account_ids = {
        "Checking": db.get_or_create_account(connection, business_id, "Checking", "checking", "Bank of America"),
        "Credit Card": db.get_or_create_account(connection, business_id, "Credit Card", "credit_card", "Bank of America"),
    }
    imported = 0
    for row in _rows(workbook_path, "Transactions"):
        account = str(row.get("Account") or "").strip()
        if account not in account_ids or not row.get("Transaction Date"):
            continue
        revenue = float(row.get("Revenue Candidate") or 0)
        expense = float(row.get("Expense Candidate") or 0)
        label = str(row.get("Treatment") or "Reconciled")
        if revenue:
            treatment = "Revenue" if revenue > 0 else "Revenue refund"
        elif expense:
            treatment = "Expense" if expense > 0 else "Expense refund"
        elif "transfer" in label.lower():
            treatment = "Transfer"
        else:
            treatment = "Excluded"
        category_id = db.get_or_create_category(connection, business_id, label, treatment)
        source_amount = float(row.get("Source Amount") or 0)
        signed = -source_amount if account == "Credit Card" else source_amount
        transaction_id, duplicate, _ = db.insert_transaction(
            connection, business_id=business_id, account_id=account_ids[account],
            transaction_date=_date(row["Transaction Date"]),
            posting_date=_date(row["Posting Date"]) if row.get("Posting Date") else None,
            description=str(row.get("Description") or ""), source_amount=source_amount,
            signed_amount=signed, source_category=str(row.get("Source Category") or ""),
            category_id=category_id, treatment=treatment, status="confirmed",
            source_file=str(row.get("Source File") or workbook_path.name),
            source_reference=str(row.get("Reference ID") or row.get("Source Line") or ""),
            notes=str(row.get("Basis") or ""), raw=row, allow_rules=False,
        )
        if not duplicate:
            imported += 1
            db.learn_rule(connection, business_id=business_id, account_id=account_ids[account],
                          pattern=db.learned_pattern(str(row.get("Description") or "")),
                          category_id=category_id, treatment=treatment, apply_existing=False)
    return {"business_id": business_id, "imported": imported}


def seed_rovar(connection, workbook_path: Path) -> dict[str, int]:
    business_id = db.get_or_create_business(connection, "Rovar Infotech LLC")
    boa_card_id = db.get_or_create_account(connection, business_id, "BOA Credit Card", "credit_card", "Bank of America", "1432")
    account_ids = {
        "BOA Checking": db.get_or_create_account(connection, business_id, "BOA Checking", "checking", "Bank of America"),
        "Truist Checking": db.get_or_create_account(connection, business_id, "Truist Checking", "checking", "Truist"),
        "BOA Credit Card": boa_card_id,
        "BOA Credit Card 1432": boa_card_id,
    }
    for number in range(1, 4):
        db.get_or_create_account(connection, business_id, f"Line of Credit {number}", "line_of_credit")

    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    category_rows = list(workbook["Categories"].iter_rows(min_row=7, values_only=True))
    for row in category_rows:
        if row and row[0] and row[1] in db.TREATMENTS:
            db.get_or_create_category(connection, business_id, str(row[0]), str(row[1]))

    imported = 0
    for row in _rows(workbook_path, "Transactions"):
        account = str(row.get("Account") or "").strip()
        if account not in account_ids or not row.get("Transaction Date"):
            continue
        source_amount = float(row.get("Source Amount") or 0)
        signed_value = row.get("Signed Amount")
        signed = float(signed_value) if isinstance(signed_value, (int, float)) else (-source_amount if "Credit Card" in account else source_amount)
        _, duplicate, _ = db.insert_transaction(
            connection, business_id=business_id, account_id=account_ids[account],
            transaction_date=_date(row["Transaction Date"]),
            posting_date=_date(row["Posting Date"]) if row.get("Posting Date") else None,
            description=str(row.get("Description") or ""), source_amount=source_amount,
            signed_amount=signed, source_category=str(row.get("Source Category") or ""),
            treatment="Needs review", status="needs_review", source_file=str(row.get("Source File") or workbook_path.name),
            source_reference=str(row.get("Source Row / Reference") or ""), notes=str(row.get("Notes") or ""),
            raw=row, allow_rules=False,
        )
        imported += int(not duplicate)
    return {"business_id": business_id, "imported": imported}


def seed_database(db_path: Path, hccl_path: Path, rovar_path: Path) -> dict[str, dict[str, int]]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        return {"HCCL": seed_hccl(connection, hccl_path), "Rovar": seed_rovar(connection, rovar_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--hccl", type=Path, required=True)
    parser.add_argument("--rovar", type=Path, required=True)
    args = parser.parse_args()
    print(seed_database(args.db, args.hccl, args.rovar))


if __name__ == "__main__":
    main()
