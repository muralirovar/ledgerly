"""Local, offline question answering over the transactions: no AI service, plain rules.

Examples: "Makesh payments 2026", "checks over 5000 to AlgebraIT", "revenue Colina sept by month",
"expenses last month by category", "amount 1250.50", "check 1042".
"""
from __future__ import annotations

import calendar
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9

STOPWORDS = {
    "a", "all", "an", "and", "any", "are", "as", "at", "bills", "did", "do", "for", "from", "get", "give", "had",
    "has", "have", "how", "i", "in", "is", "it", "list", "me", "much", "my", "of", "on", "paid", "pay", "pays",
    "please", "search", "show", "so", "that", "the", "their", "them", "there", "to", "total", "transaction",
    "transactions", "was", "were", "what", "when", "where", "which", "with", "find", "many", "made", "make",
    "sum", "amount", "amounts", "by", "per", "during", "within",
}
KIND_WORDS = {
    "revenue": "revenue", "revenues": "revenue", "income": "revenue", "deposit": "revenue", "deposits": "revenue",
    "sales": "revenue", "received": "revenue",
    "expense": "expense", "expenses": "expense", "spent": "expense", "spend": "expense", "spending": "expense",
    "payment": "out", "payments": "out", "payout": "out", "payouts": "out",
    "loan": "loan", "loans": "loan", "transfer": "transfer", "transfers": "transfer",
    "refund": "refund", "refunds": "refund",
}
GROUP_WORDS = {
    "month": "Month", "months": "Month", "monthly": "Month",
    "vendor": "Name", "vendors": "Name", "party": "Name", "parties": "Name", "payee": "Name", "payees": "Name",
    "name": "Name", "category": "Category", "categories": "Category", "year": "Year", "yearly": "Year",
    "business": "Business", "businesses": "Business", "account": "Account", "accounts": "Account",
}
REVENUE_TREATMENTS = ("Revenue",)
EXPENSE_TREATMENTS = ("Expense",)
TREATMENT_PHRASES = (
    (r"loan draws?", ["Loan draw"]), (r"principal repayments?|loan repayments?", ["Principal repayment"]),
    (r"loan receivables?", ["Loan receivable"]), (r"receivable repayments?", ["Receivable repayment"]),
    (r"owner draws?", ["Owner draw"]), (r"owner contributions?", ["Owner contribution"]),
    (r"(?:internal |account )?transfers?", ["Transfer"]), (r"excluded", ["Excluded"]),
    (r"revenue refunds?", ["Revenue refund"]), (r"expense refunds?", ["Expense refund"]),
)
LOAN_TREATMENTS = ("Loan draw", "Principal repayment", "Loan receivable", "Receivable repayment")


@dataclass
class Query:
    text: str
    terms: list[str] = field(default_factory=list)
    kind: str = ""
    start: str = ""
    end: str = ""
    min_amount: float | None = None
    max_amount: float | None = None
    exact_amount: float | None = None
    check_number: str = ""
    checks_only: bool = False
    needs_review: bool = False
    group_by: str = ""
    all_businesses: bool = False
    category: str = ""
    category_names: list[str] = field(default_factory=list)
    category_words: list[str] = field(default_factory=list)
    treatments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last).isoformat()


def _number(raw: str) -> float:
    return float(raw.replace(",", "").replace("$", ""))


def parse(question: str, categories: list[str] | None = None, business_names: list[str] | None = None,
          today: date | None = None) -> Query:
    today = today or date.today()
    query = Query(text=question)
    text = f" {question.lower()} "

    def take(pattern: str) -> re.Match | None:
        nonlocal text
        match = re.search(pattern, text)
        if match:
            text = text[:match.start()] + " " + text[match.end():]
        return match

    # whole-portfolio and review words
    if take(r"\b(all businesses|every business|all companies|everywhere|combined)\b"):
        query.all_businesses = True
    if take(r"\bneeds? review\b|\bunreviewed\b|\buncategori[sz]ed\b"):
        query.needs_review = True
    if take(r"\bchecks?\b(?!\s*#?\s*\d)|\bcheques?\b"):
        query.checks_only = True
    match = take(r"\b(?:check|cheque|chk)\s*(?:no\.?|number|#)?\s*#?\s*(\d{2,8})\b")
    if match:
        query.check_number = match.group(1)
        query.checks_only = True

    # amounts
    for pattern, attr in ((r"(?:over|above|more than|greater than|at least|>=?|bigger than)\s*\$?\s*([\d,]+(?:\.\d+)?)", "min_amount"),
                          (r"(?:under|below|less than|at most|<=?|smaller than)\s*\$?\s*([\d,]+(?:\.\d+)?)", "max_amount")):
        match = take(pattern)
        if match:
            setattr(query, attr, _number(match.group(1)))
    match = take(r"between\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(?:and|-|to)\s*\$?\s*([\d,]+(?:\.\d+)?)")
    if match:
        query.min_amount, query.max_amount = sorted((_number(match.group(1)), _number(match.group(2))))
    match = take(r"\$\s*([\d,]+(?:\.\d+)?)|\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\b|\b(\d+\.\d{2})\b")
    if match and query.min_amount is None and query.max_amount is None:
        query.exact_amount = _number(next(group for group in match.groups() if group))

    # dates
    year = None
    match = take(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
    if match:
        query.start, query.end = _month_bounds(int(match.group(1)), int(match.group(2)))
    if take(r"\blast month\b"):
        first = date(today.year, today.month, 1) - timedelta(days=1)
        query.start, query.end = _month_bounds(first.year, first.month)
    if take(r"\bthis month\b"):
        query.start, query.end = _month_bounds(today.year, today.month)
    if take(r"\blast year\b"):
        query.start, query.end = f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"
    if take(r"\b(this year|ytd|year to date)\b"):
        query.start, query.end = f"{today.year}-01-01", today.isoformat()
    match = take(r"\b(20\d{2})\b")
    if match:
        year = int(match.group(1))
    if not query.start:
        month_match = take(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
                           r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\b")
        if month_match:
            number = MONTHS[month_match.group(1)]
            chosen = year or (today.year if number <= today.month else today.year - 1)
            query.start, query.end = _month_bounds(chosen, number)
        elif year:
            query.start, query.end = f"{year}-01-01", f"{year}-12-31"

    # grouping
    match = take(r"\b(?:by|per|group(?:ed)? by|each)\s+(month|months|monthly|vendor|vendors|party|parties|payee|payees|"
                 r"name|category|categories|year|yearly|business|businesses|account|accounts)\b")
    if match:
        query.group_by = GROUP_WORDS[match.group(1)]
    elif take(r"\bmonthly\b"):
        query.group_by = "Month"

    # business names mentioned -> handled by the caller as a filter term
    for name in business_names or []:
        if name.lower() in text:
            query.terms.append(name.lower())
            text = text.replace(name.lower(), " ")

    # a category named in full wins, unless it is only part of a longer treatment phrase ("loan receivable")
    def inside_treatment_phrase(name: str) -> bool:
        for pattern, _ in TREATMENT_PHRASES:
            found = re.search(rf"\b{pattern}\b", text)
            if found and name.lower() in found.group(0) and len(found.group(0)) > len(name):
                return True
        return False

    for name in sorted(categories or [], key=len, reverse=True):
        if len(name) >= 3 and name.lower() in text and not inside_treatment_phrase(name):
            query.category = name
            query.category_names = [other for other in (categories or []) if other.lower() == name.lower()][:1]
            text = text.replace(name.lower(), " ")
            break

    # treatments named outright (loan draw, internal transfer, owner draw ...)
    for pattern, names in TREATMENT_PHRASES:
        if take(rf"\b{pattern}\b"):
            query.treatments += [name for name in names if name not in query.treatments]

    # a part of a category name: every leftover word must belong to the same category (gas, fee, soft, "it staffing")
    if not query.category and categories:
        words = [w for w in re.findall(r"[a-z0-9]+", text) if w not in STOPWORDS and w not in KIND_WORDS]
        if words:
            def word_hits(word: str, name_words: list[str]) -> bool:
                stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
                for nw in name_words:
                    if nw == word or nw == stem:
                        return True
                    if len(word) >= 3 and (nw.startswith(word) or nw.startswith(stem)):
                        return True
                    if len(word) >= 4 and word in nw:
                        return True
                return False
            found = []
            for name in categories:
                name_words = re.findall(r"[a-z0-9]+", name.lower())
                if all(word_hits(w, name_words) for w in words) and name not in found:
                    found.append(name)
            if 0 < len(found) <= 10:
                query.category_names = found
                query.category = found[0] if len(found) == 1 else f"{len(found)} matching categories"
                query.category_words = words
                for w in words:
                    text = re.sub(rf"\b{re.escape(w)}\b", " ", text, count=1)

    # kind words
    for word in re.findall(r"[a-z]+", text):
        if word in KIND_WORDS and not query.kind:
            query.kind = KIND_WORDS[word]
            text = re.sub(rf"\b{word}\b", " ", text, count=1)

    for word in re.findall(r"[a-z0-9&.'-]+", text):
        cleaned = word.strip(".'-")
        if cleaned and cleaned not in STOPWORDS:
            query.terms.append(cleaned)
    return query


def describe(query: Query) -> list[str]:
    parts = []
    if query.kind:
        parts.append({"revenue": "Revenue", "expense": "Expenses", "out": "Money out", "loan": "Loan activity",
                      "transfer": "Transfers", "refund": "Refunds"}[query.kind])
    if query.treatments:
        parts.append("Treatment: " + " / ".join(query.treatments))
    if query.terms:
        parts.append("Text contains: " + ", ".join(query.terms))
    if query.category:
        parts.append(f"Category: {query.category}")
    if query.start:
        parts.append(f"Dates: {query.start} → {query.end}")
    if query.exact_amount is not None:
        parts.append(f"Amount = {query.exact_amount:,.2f}")
    if query.min_amount is not None:
        parts.append(f"Amount ≥ {query.min_amount:,.2f}")
    if query.max_amount is not None:
        parts.append(f"Amount ≤ {query.max_amount:,.2f}")
    if query.check_number:
        parts.append(f"Check #{query.check_number}")
    elif query.checks_only:
        parts.append("Checks only")
    if query.needs_review:
        parts.append("Needs review")
    if query.group_by:
        parts.append(f"Grouped by {query.group_by.lower()}")
    if query.all_businesses:
        parts.append("All businesses")
    return parts


def run(connection: sqlite3.Connection, query: Query, business_id: int | None, limit: int = 2000,
        allowed_ids: list[int] | None = None) -> list[dict[str, Any]]:
    where, params = ["t.status != 'split'"], []
    if business_id is not None and not query.all_businesses:
        where.append("t.business_id = ?")
        params.append(business_id)
    elif allowed_ids is not None:
        where.append(f"t.business_id IN ({','.join('?' * len(allowed_ids)) or 'NULL'})")
        params += [int(i) for i in allowed_ids]
    if query.start:
        where.append("t.transaction_date BETWEEN ? AND ?")
        params += [query.start, query.end]
    if query.kind == "revenue":
        where.append("t.treatment = 'Revenue'")
    elif query.kind == "expense":
        where.append("t.treatment = 'Expense'")
    elif query.kind == "out":
        where.append("t.signed_amount < 0")
    elif query.kind == "loan":
        where.append(f"t.treatment IN ({','.join('?' * len(LOAN_TREATMENTS))})")
        params += list(LOAN_TREATMENTS)
    elif query.kind == "transfer":
        where.append("t.treatment = 'Transfer'")
    elif query.kind == "refund":
        where.append("t.treatment IN ('Revenue refund', 'Expense refund')")
    if query.treatments:
        where.append(f"t.treatment IN ({','.join('?' * len(query.treatments))})")
        params += query.treatments
    if query.needs_review:
        where.append("t.status = 'needs_review'")
    if query.exact_amount is not None:
        where.append("ABS(ABS(t.signed_amount) - ?) < 0.005")
        params.append(query.exact_amount)
    if query.min_amount is not None:
        where.append("ABS(t.signed_amount) >= ?")
        params.append(query.min_amount)
    if query.max_amount is not None:
        where.append("ABS(t.signed_amount) <= ?")
        params.append(query.max_amount)
    if query.category_names:
        where.append(f"LOWER(COALESCE(c.name, '')) IN ({','.join('?' * len(query.category_names))})")
        params += [name.lower() for name in query.category_names]
    if query.check_number:
        where.append("EXISTS (SELECT 1 FROM check_register r WHERE r.transaction_id = t.id AND r.check_number = ?)")
        params.append(query.check_number.lstrip("0") or "0")
    elif query.checks_only:
        where.append("EXISTS (SELECT 1 FROM check_register r WHERE r.transaction_id = t.id)")

    sql = f"""
        SELECT t.id, t.business_id, b.name AS Business, t.transaction_date AS Date, t.description AS Description,
               COALESCE(t.counterparty, '') AS Name, COALESCE(c.name, '') AS Category, t.treatment AS Treatment,
               t.signed_amount AS Amount, a.name AS Account, COALESCE(t.notes, '') AS Note,
               (SELECT GROUP_CONCAT(TRIM(COALESCE(r.check_number, '') || ' ' || COALESCE(r.payee, '') || ' ' ||
                                         COALESCE(r.memo, '')), ' | ')
                  FROM check_register r WHERE r.transaction_id = t.id) AS Check_info
          FROM transactions t
          JOIN businesses b ON b.id = t.business_id
          JOIN accounts a ON a.id = t.account_id
          LEFT JOIN categories c ON c.id = t.category_id
         WHERE {' AND '.join(where)}
         ORDER BY t.transaction_date DESC, t.id DESC
    """
    rows = [dict(row) for row in connection.execute(sql, params)]
    if query.terms:
        wanted = [_squash(term) for term in query.terms]
        kept = []
        for row in rows:
            haystack = _squash(" ".join(str(row[key] or "") for key in
                                        ("Business", "Description", "Name", "Category", "Note", "Check_info", "Account")))
            if all(term in haystack for term in wanted):
                kept.append(row)
        rows = kept
    if not rows and query.category_names and query.category_words:
        from dataclasses import replace
        return run(connection, replace(query, category="", category_names=[], category_words=[],
                                       terms=query.category_words + query.terms), business_id, limit, allowed_ids)
    for row in rows:
        row["Check"] = row.pop("Check_info") or ""
    return rows[:limit]


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    money_in = sum(row["Amount"] for row in rows if row["Amount"] > 0)
    money_out = -sum(row["Amount"] for row in rows if row["Amount"] < 0)
    return {"count": len(rows), "in": round(money_in, 2), "out": round(money_out, 2),
            "net": round(money_in - money_out, 2)}


def group(rows: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if by == "Month":
            key = row["Date"][:7]
        elif by == "Year":
            key = row["Date"][:4]
        elif by == "Name":
            key = row["Name"] or row["Description"]
        else:
            key = row.get(by) or "(none)"
        bucket = buckets.setdefault(key, {by: key, "Count": 0, "In": 0.0, "Out": 0.0})
        bucket["Count"] += 1
        if row["Amount"] > 0:
            bucket["In"] += row["Amount"]
        else:
            bucket["Out"] += -row["Amount"]
    result = []
    for bucket in buckets.values():
        bucket["In"], bucket["Out"] = round(bucket["In"], 2), round(bucket["Out"], 2)
        bucket["Net"] = round(bucket["In"] - bucket["Out"], 2)
        result.append(bucket)
    result.sort(key=lambda item: item[by], reverse=by in ("Month", "Year"))
    if by not in ("Month", "Year"):
        result.sort(key=lambda item: -(item["In"] + item["Out"]))
    return result
