from __future__ import annotations

import sqlite3
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import db


def _sheet(workbook: Workbook, title: str, rows: list[dict]) -> None:
    sheet = workbook.create_sheet(title)
    if not rows:
        sheet.append(["No records"])
        return
    headers = list(rows[0])
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17324D")
    for row in rows:
        sheet.append([row.get(header) for header in headers])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, header in enumerate(headers, start=1):
        width = max(len(str(header)), *(len(str(row.get(header, "") or "")) for row in rows[:500]))
        sheet.column_dimensions[get_column_letter(index)].width = min(width + 2, 55)


def business_workbook(connection: sqlite3.Connection, business_id: int) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    transactions = db.list_transactions(connection, business_id=business_id, limit=100000)
    _sheet(workbook, "Transactions", transactions)
    _sheet(workbook, "Category Summary", db.category_summary(connection, business_id))
    _sheet(workbook, "Accounts", db.account_summaries(connection, business_id))
    _sheet(workbook, "LOC Activity", db.list_loan_events(connection, business_id))
    _sheet(workbook, "Rules", db.list_rules(connection, business_id))
    _sheet(workbook, "Import Log", db.list_import_batches(connection, business_id))
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def tax_prep_workbook(connection: sqlite3.Connection, business_id: int, year: int) -> bytes:
    transactions = [
        row for row in db.list_transactions(connection, business_id=business_id, limit=100000)
        if str(row.get("transaction_date", "")).startswith(f"{year}-")
    ]
    revenue: list[dict] = []
    expenses: list[dict] = []
    review: list[dict] = []
    excluded: list[dict] = []
    category_totals: dict[tuple[str, str], float] = {}
    for row in transactions:
        treatment = row.get("treatment")
        category = row.get("category") or "Uncategorized"
        signed = float(row.get("signed_amount") or 0)
        if treatment in {"Revenue", "Revenue refund"}:
            amount = signed
            revenue.append({**row, "report_amount": amount})
            category_totals[("Revenue", category)] = category_totals.get(("Revenue", category), 0) + amount
        elif treatment in {"Expense", "Expense refund"}:
            amount = abs(signed) if treatment == "Expense" else -abs(signed)
            expenses.append({**row, "report_amount": amount})
            category_totals[("Expense", category)] = category_totals.get(("Expense", category), 0) + amount
        elif row.get("status") == "needs_review":
            review.append(row)
        else:
            excluded.append(row)
    totals = [
        {"type": kind, "category": category, "amount": amount}
        for (kind, category), amount in sorted(category_totals.items())
    ]
    summary = [{
        "tax_year": year,
        "revenue": sum(float(row["report_amount"]) for row in revenue),
        "expenses": sum(float(row["report_amount"]) for row in expenses),
        "net": sum(float(row["report_amount"]) for row in revenue) - sum(float(row["report_amount"]) for row in expenses),
        "needs_review": len(review),
        "excluded_transfer_or_loan": len(excluded),
    }]
    workbook = Workbook()
    workbook.remove(workbook.active)
    _sheet(workbook, "Tax Summary", summary)
    _sheet(workbook, "Category Totals", totals)
    _sheet(workbook, "Revenue Detail", revenue)
    _sheet(workbook, "Expense Detail", expenses)
    _sheet(workbook, "Needs Review", review)
    _sheet(workbook, "Excluded Transfers Loans", excluded)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
