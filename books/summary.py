"""Preliminary revenue and expense summary (on screen and as an Excel sheet)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import mileage

EXCLUDED_TREATMENTS = ("Transfer", "Owner contribution", "Owner draw", "Loan draw", "Principal repayment",
                       "Loan receivable", "Receivable repayment", "Excluded", "Needs review")
ACCOUNT_LABELS = {"checking": ("Checking inflows", "Checking outflows"),
                  "credit_card": ("Credit-card credits", "Credit-card charges"),
                  "line_of_credit": ("Line-of-credit draws", "Line-of-credit payments")}


def preliminary(connection: sqlite3.Connection, business_id: int, start: str, end: str) -> dict[str, Any]:
    rows = [dict(row) for row in connection.execute(
        """SELECT t.treatment, t.signed_amount AS amount, COALESCE(c.name, 'Uncategorized') AS category, a.account_type
             FROM transactions t JOIN accounts a ON a.id = t.account_id LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.business_id = ? AND t.status != 'split' AND t.transaction_date BETWEEN ? AND ?""",
        (business_id, start, end))]

    def bucket(treatments: tuple[str, ...], sign: int, label_suffix: str) -> list[dict[str, Any]]:
        groups: dict[str, list[float]] = {}
        for row in rows:
            if row["treatment"] in treatments:
                groups.setdefault(row["category"], []).append(sign * row["amount"])
        return sorted(({"label": name if label_suffix.strip() in name.lower() else f"{name}{label_suffix}", "count": len(values), "amount": round(sum(values), 2)}
                       for name, values in groups.items()), key=lambda item: -abs(item["amount"]))

    revenue = bucket(("Revenue",), 1, " revenue")
    refunds = [row["amount"] for row in rows if row["treatment"] == "Revenue refund"]
    if refunds:
        revenue.append({"label": "Revenue refunds", "count": len(refunds), "amount": round(sum(refunds), 2)})
    expenses = bucket(("Expense", "Expense refund"), -1, " expense")
    excluded = []
    for treatment in EXCLUDED_TREATMENTS:
        items = [abs(row["amount"]) for row in rows if row["treatment"] == treatment]
        if items:
            excluded.append({"label": treatment if treatment != "Needs review" else "Needs review (not yet classified)",
                             "count": len(items), "amount": round(sum(items), 2)})
    revenue_total = round(sum(item["amount"] for item in revenue), 2)
    expense_total = round(sum(item["amount"] for item in expenses), 2)
    controls = []
    for account_type, (inflow_label, outflow_label) in ACCOUNT_LABELS.items():
        inflow = [row["amount"] for row in rows if row["account_type"] == account_type and row["amount"] > 0]
        outflow = [-row["amount"] for row in rows if row["account_type"] == account_type and row["amount"] < 0]
        if inflow or outflow:
            controls.append({"label": inflow_label, "count": len(inflow), "amount": round(sum(inflow), 2)})
            controls.append({"label": outflow_label, "count": len(outflow), "amount": round(sum(outflow), 2)})
    review = sum(1 for row in rows if row["treatment"] == "Needs review")
    method = [
        "Revenue counts transactions treated as Revenue, less Revenue refunds. Expenses count transactions treated as Expense, "
        "net of Expense refunds, grouped by category.",
        "Transfers between your own accounts, owner contributions and draws, loan draws and repayments, loan receivables and "
        "excluded items are not revenue or expense and are listed on the right.",
        f"{review} transaction(s) still need review and are not in the totals." if review else
        "No transactions are waiting for review in this period.",
    ]
    return {"start": start, "end": end, "revenue": revenue, "expenses": expenses, "excluded": excluded,
            "revenue_total": revenue_total, "expense_total": expense_total,
            "net": round(revenue_total - expense_total, 2), "controls": controls, "method": method,
            "revenue_count": sum(item["count"] for item in revenue),
            "expense_count": sum(item["count"] for item in expenses)}


HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
MONEY = '$#,##0.00;[Red]($#,##0.00);"-"'


def _head(sheet, row: int, column: int, labels: list[str]) -> None:
    for offset, label in enumerate(labels):
        cell = sheet.cell(row=row, column=column + offset, value=label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center")


def _lines(sheet, row: int, column: int, items: list[dict[str, Any]], total_label: str = "",
           total: float | None = None, total_count: int | None = None) -> int:
    for item in items:
        sheet.cell(row=row, column=column, value=item["label"])
        sheet.cell(row=row, column=column + 1, value=item["count"])
        sheet.cell(row=row, column=column + 2, value=item["amount"]).number_format = MONEY
        row += 1
    if total_label:
        for offset, value in enumerate((total_label, total_count, total)):
            cell = sheet.cell(row=row, column=column + offset, value=value)
            cell.font = Font(bold=True)
            if offset == 2:
                cell.number_format = MONEY
        row += 1
    return row


def summary_workbook(connection: sqlite3.Connection, business_id: int, business_name: str, start: str, end: str,
                     year: int) -> bytes:
    data = preliminary(connection, business_id, start, end)
    book = Workbook()
    sheet = book.active
    sheet.title = "Summary"
    sheet["A1"] = f"Preliminary revenue and expense summary — {business_name}"
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"] = f"{start} to {end} | USD | Based on classified transactions"
    sheet["A2"].font = Font(italic=True, color="666666")
    _head(sheet, 4, 1, ["Preliminary summary", "", "Amount"])
    for index, (label, value) in enumerate((("Net revenue", data["revenue_total"]), ("Expenses", data["expense_total"]),
                                            ("Net before review items", data["net"]))):
        sheet.cell(row=5 + index, column=1, value=label).font = Font(bold=index == 2)
        cell = sheet.cell(row=5 + index, column=3, value=value)
        cell.number_format, cell.font = MONEY, Font(bold=index == 2)
    _head(sheet, 4, 5, ["Items excluded or requiring treatment", "Count", "Amount"])
    _lines(sheet, 5, 5, data["excluded"])
    top = max(10, 5 + len(data["excluded"]) + 1)
    _head(sheet, top, 1, ["Revenue detail", "Count", "Amount"])
    _head(sheet, top, 5, ["Expense detail", "Count", "Amount"])
    end_revenue = _lines(sheet, top + 1, 1, data["revenue"], "Total net revenue", data["revenue_total"], data["revenue_count"])
    end_expense = _lines(sheet, top + 1, 5, data["expenses"], "Total expenses", data["expense_total"], data["expense_count"])
    row = max(end_revenue, end_expense) + 2
    _head(sheet, row, 1, ["Cash-flow controls", "Count", "Calculated"])
    row = _lines(sheet, row + 1, 1, data["controls"]) + 1
    sheet.cell(row=row, column=1, value="Method").font = Font(bold=True)
    for note in data["method"]:
        row += 1
        cell = sheet.cell(row=row, column=1, value=note)
        cell.font = Font(italic=True, color="444444", size=9)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        sheet.row_dimensions[row].height = 30
    for column, width in zip("ABCDEFG", (42, 9, 16, 3, 42, 9, 16)):
        sheet.column_dimensions[column].width = width

    miles = book.create_sheet("Tax & business miles")
    rates = mileage.get_rates(connection, year)
    trips = mileage.list_trips(connection, business_id, year)
    miles["A1"] = f"Tax and business miles — {business_name} — {year}"
    miles["A1"].font = Font(bold=True, size=14)
    _head(miles, 3, 1, ["Type", "Trips", "Miles", "Rate per mile", "Deduction"])
    summary_rows = mileage.summarize(trips, rates)
    for index, item in enumerate(summary_rows):
        for column, key in enumerate(("Type", "Trips", "Miles", "Rate per mile", "Deduction"), start=1):
            cell = miles.cell(row=4 + index, column=column, value=item[key])
            if key in ("Rate per mile", "Deduction"):
                cell.number_format = '$#,##0.00#' if key == "Rate per mile" else MONEY
    total_row = 4 + len(summary_rows)
    miles.cell(row=total_row, column=1, value="Total deduction").font = Font(bold=True)
    cell = miles.cell(row=total_row, column=5, value=round(sum(item["Deduction"] for item in summary_rows), 2))
    cell.number_format, cell.font = MONEY, Font(bold=True)
    log_row = total_row + 2
    _head(miles, log_row, 1, ["Date", "Type", "Miles", "From", "To", "Purpose", "Notes"])
    for index, trip in enumerate(sorted(trips, key=lambda item: item["trip_date"])):
        for column, value in enumerate((trip["trip_date"], trip["kind"], trip["miles"], trip["start_place"],
                                        trip["end_place"], trip["purpose"], trip["notes"]), start=1):
            miles.cell(row=log_row + 1 + index, column=column, value=value)
    for column, width in zip("ABCDEFG", (14, 12, 10, 26, 26, 34, 30)):
        miles.column_dimensions[column].width = width
    log = book.create_sheet("Business miles")
    for column, label in enumerate(("Trip Date", "Purpose", "Miles"), start=1):
        cell = log.cell(row=1, column=column, value=label)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEAD_FILL
        cell.alignment = Alignment(horizontal="center")
    business_trips = sorted((trip for trip in trips if trip["kind"] == "Business"), key=lambda item: item["trip_date"])
    for index, trip in enumerate(business_trips, start=2):
        log.cell(row=index, column=1, value=datetime.strptime(trip["trip_date"], "%Y-%m-%d")).number_format = "mm/dd/yy"
        log.cell(row=index, column=2, value=trip["purpose"])
        log.cell(row=index, column=3, value=trip["miles"])
    total_at = len(business_trips) + 3
    log.cell(row=total_at, column=1, value="Total miles").font = Font(bold=True)
    log.cell(row=total_at, column=3, value=f"=SUM(C2:C{max(2, total_at - 2)})").font = Font(bold=True)
    for column, width in zip("ABC", (14, 34, 10)):
        log.column_dimensions[column].width = width
    output = BytesIO()
    book.save(output)
    return output.getvalue()
