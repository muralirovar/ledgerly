"""Read invoices and receipts: pull the total, date, vendor and number out of a PDF's text.

Only PDFs that contain real text are understood. Scans and phone photos return nothing, and the
caller falls back to attaching them by hand. Nothing here writes to the database.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO
from typing import Any

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_AMOUNT = re.compile(r"(?<![\d.])\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})(?!\d)")
_TOTAL_WORDS = re.compile(r"(grand\s+total|amount\s+due|balance\s+due|total\s+due|total\s+amount|amount\s+paid|"
                          r"payment\s+amount|\btotal\b)", re.I)
_SKIP_WORDS = re.compile(r"\b(sub\s*total|subtotal|tax|shipping|discount|tip)\b", re.I)
_INVOICE = re.compile(r"(?:invoice|receipt|order|inv)\s*(?:#|no\.?|number)\s*:?\s*([A-Z0-9][A-Z0-9-]{2,})", re.I)
_NOT_VENDOR = re.compile(r"^(invoice|receipt|tax invoice|statement|bill|page|date|total|amount|order|payment|thank)", re.I)


def extract_text(pdf_bytes: bytes) -> str:
    """The text printed in a PDF, or an empty string if it has none or cannot be read."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:6]).strip()
    except Exception:
        return ""


def _dates(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text):
        found.append(_iso(int(m[1]), int(m[2]), int(m[3])))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        year = int(m[3]) + (2000 if int(m[3]) < 100 else 0)
        found.append(_iso(year, int(m[1]), int(m[2])))
    for m in re.finditer(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b", text):
        month = _MONTHS.get(m[1].lower())
        if month:
            found.append(_iso(int(m[3]), month, int(m[2])))
    return [d for d in dict.fromkeys(found) if d]


def _iso(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _money(raw: str) -> float:
    return round(float(raw.replace(",", "")), 2)


def parse_document(text: str) -> dict[str, Any]:
    """Best-guess total, other amounts, dates, vendor and invoice number from document text."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    amounts: list[float] = []
    total = None
    for line in lines:
        for m in _AMOUNT.finditer(line):
            value = _money(m[1])
            if value > 0 and value not in amounts:
                amounts.append(value)
        if _TOTAL_WORDS.search(line) and not _SKIP_WORDS.search(line):
            values = [_money(m[1]) for m in _AMOUNT.finditer(line)]
            if values:
                total = values[-1]
    if total is None and amounts:
        total = max(amounts)
    vendor = ""
    for line in lines[:8]:
        if len(line) >= 3 and re.search(r"[A-Za-z]{3}", line) and not _NOT_VENDOR.match(line) \
                and not _AMOUNT.search(line) and not re.fullmatch(r"[\d/\-.\s]+", line):
            vendor = re.sub(r"\s{2,}", " ", line)[:60]
            break
    invoice = _INVOICE.search(text or "")
    return {"total": total, "amounts": amounts[:20], "dates": _dates(text or "")[:6], "vendor": vendor,
            "invoice": invoice[1] if invoice else "", "has_text": bool(lines)}


def match_candidates(connection, business_id: int, parsed: dict[str, Any], *, window_days: int = 60) -> list[dict[str, Any]]:
    """Transactions that could belong to a document, best first, with the reason for each."""
    amounts = ([parsed["total"]] if parsed.get("total") else []) + [a for a in parsed.get("amounts", []) if a != parsed.get("total")]
    amounts = amounts[:12]
    if not amounts:
        return []
    marks = ",".join("?" for _ in amounts)
    clauses = " OR ".join("ABS(ABS(t.signed_amount) - ?) < 0.005" for _ in amounts)
    rows = connection.execute(
        f"""SELECT t.id, t.transaction_date, t.description, t.signed_amount, t.status, t.treatment, a.name AS account
            FROM transactions t JOIN accounts a ON a.id = t.account_id
            WHERE t.business_id = ? AND t.split_parent_id IS NULL AND t.status <> 'split' AND ({clauses})""",
        [business_id, *amounts]).fetchall()
    doc_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in parsed.get("dates", [])]
    vendor_words = [w for w in re.findall(r"[A-Za-z]{4,}", parsed.get("vendor", "").lower())]
    scored = []
    for row in rows:
        amount = abs(float(row["signed_amount"]))
        score, why = 0.0, []
        if parsed.get("total") and abs(amount - parsed["total"]) < 0.005:
            score += 5; why.append("amount matches the total")
        else:
            score += 2; why.append("amount appears in the document")
        if doc_dates:
            when = datetime.strptime(row["transaction_date"], "%Y-%m-%d").date()
            gap = min(abs((when - d).days) for d in doc_dates)
            if gap <= window_days:
                score += max(0.0, 3 - gap / 20); why.append("date within %d day(s)" % gap)
            else:
                score -= 2
        if vendor_words and any(w in row["description"].lower() for w in vendor_words):
            score += 2; why.append("vendor name in the bank text")
        if row["status"] == "needs_review":
            score += 0.5
        scored.append({**dict(row), "score": round(score, 2), "why": ", ".join(why)})
    return sorted(scored, key=lambda r: (-r["score"], r["transaction_date"]))[:6]
