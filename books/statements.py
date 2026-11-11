from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass(frozen=True)
class ClearedCheck:
    cleared_date: str
    check_number: str
    amount: float


def _money(text: str) -> float:
    return float(text.replace("$", "").replace(",", "").strip())


def parse_boa_check_rows(text: str) -> list[tuple[str, str, float]]:
    """Parse BOA compact check rows, including sequence-gap markers such as 255*."""
    return [
        (cleared, number, _money(amount))
        for cleared, number, amount in re.findall(
            r"(\d{2}/\d{2}/\d{2})\s*(\d+)\*?\s+-?([\d,]+\.\d{2})", text
        )
    ]


def detect_bank(pdf_bytes: bytes) -> str:
    text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf_bytes)).pages[:2])
    upper = text.upper()
    if "TRUIST" in upper:
        return "Truist"
    if "BANK OF AMERICA" in upper:
        return "Bank of America"
    return "Other / unknown"


def parse_truist_statement(pdf_bytes: bytes) -> dict[str, Any]:
    reader = PdfReader(BytesIO(pdf_bytes))
    if not reader.pages:
        raise ValueError("The statement has no pages.")
    return parse_truist_text(reader.pages[0].extract_text() or "", len(reader.pages))


def parse_truist_text(first_page: str, page_count: int) -> dict[str, Any]:
    if "TRUIST" not in first_page.upper():
        raise ValueError("This does not appear to be a Truist statement.")

    statement_match = re.search(r"For\s+(\d{2}/\d{2}/\d{4})", first_page, flags=re.IGNORECASE)
    if not statement_match:
        raise ValueError("The statement date could not be found.")
    statement_date = datetime.strptime(statement_match.group(1), "%m/%d/%Y").date()

    account_match = re.search(r"BUSINESS\s+CHECKING\s+(\d{4,})", first_page, flags=re.IGNORECASE)
    account_last4 = account_match.group(1)[-4:] if account_match else ""
    previous_match = re.search(r"previous balance as of\s+\d{2}/\d{2}/\d{4}\s+\$?([\d,]+\.\d{2})", first_page, flags=re.IGNORECASE)
    closing_match = re.search(r"new balance as of\s+\d{2}/\d{2}/\d{4}\s+=?\s*\$?([\d,]+\.\d{2})", first_page, flags=re.IGNORECASE)
    total_match = re.search(r"T\s*o\s*t\s*al\s+c\s*h\s*e\s*c\s*k\s*s\s*=\s*\$?([\d,]+\.\d{2})", first_page, flags=re.IGNORECASE)

    lines = first_page.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().lower().replace(" ", "") == "checks"), None)
    end = next((i for i, line in enumerate(lines) if i > (start or 0) and "withdrawals" in line.lower().replace(" ", "")), len(lines))
    check_text = " ".join(lines[(start or 0) + 1:end])
    matches = re.findall(r"(\d{2}/\d{2})\s+\*?(\d+)\s+([\d,]+\.\d{2})", check_text)
    checks: list[ClearedCheck] = []
    for month_day, number, amount in matches:
        parsed = datetime.strptime(f"{month_day}/{statement_date.year}", "%m/%d/%Y").date()
        checks.append(ClearedCheck(parsed.isoformat(), number, _money(amount)))

    return {
        "bank": "Truist",
        "statement_date": statement_date.isoformat(),
        "account_last4": account_last4,
        "opening_balance": _money(previous_match.group(1)) if previous_match else None,
        "closing_balance": _money(closing_match.group(1)) if closing_match else None,
        "check_total": _money(total_match.group(1)) if total_match else sum(item.amount for item in checks),
        "checks": [asdict(item) for item in checks],
        "page_count": page_count,
    }


def parse_boa_statement(pdf_bytes: bytes) -> dict[str, Any]:
    reader = PdfReader(BytesIO(pdf_bytes))
    if not reader.pages:
        raise ValueError("The statement has no pages.")
    return parse_boa_text("\n".join((page.extract_text() or "") for page in reader.pages), len(reader.pages))


def parse_boa_text(text: str, page_count: int) -> dict[str, Any]:
    if "BANK OF AMERICA" not in text.upper():
        raise ValueError("This does not appear to be a Bank of America statement.")

    period_match = re.search(
        r"for\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s+to\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        text,
    )
    if not period_match:
        raise ValueError("The Bank of America statement period could not be found.")
    statement_start = datetime.strptime(period_match.group(1), "%B %d, %Y").date()
    statement_end = datetime.strptime(period_match.group(2), "%B %d, %Y").date()

    account_match = re.search(r"Account number:\s*([\d ]{4,})", text, flags=re.IGNORECASE)
    account_digits = re.sub(r"\D", "", account_match.group(1)) if account_match else ""
    opening_match = re.search(
        r"Beginning balance on\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s*\$?([\d,]+\.\d{2})",
        text,
    )
    closing_match = re.search(
        r"Ending balance on\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s*\$?([\d,]+\.\d{2})",
        text,
    )

    checks_section = re.search(
        r"Checks\s*Date\s*Check\s*#\s*Amount(.*?)Total checks\s*-?\$?([\d,]+\.\d{2})",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    checks: list[ClearedCheck] = []
    check_total = 0.0
    if checks_section:
        check_total = _money(checks_section.group(2))
        for cleared, number, amount in parse_boa_check_rows(checks_section.group(1)):
            parsed_date = datetime.strptime(cleared, "%m/%d/%y").date()
            checks.append(ClearedCheck(parsed_date.isoformat(), number, amount))

    return {
        "bank": "Bank of America",
        "statement_start": statement_start.isoformat(),
        "statement_date": statement_end.isoformat(),
        "account_last4": account_digits[-4:],
        "opening_balance": _money(opening_match.group(1)) if opening_match else None,
        "closing_balance": _money(closing_match.group(1)) if closing_match else None,
        "check_total": check_total or sum(item.amount for item in checks),
        "checks": [asdict(item) for item in checks],
        "page_count": page_count,
    }


def parse_statement(pdf_bytes: bytes) -> dict[str, Any]:
    bank = detect_bank(pdf_bytes)
    if bank == "Truist":
        return parse_truist_statement(pdf_bytes)
    if bank == "Bank of America":
        return parse_boa_statement(pdf_bytes)
    raise ValueError("The bank layout is not supported yet.")


def _image_png(image: Any) -> bytes:
    output = BytesIO()
    if image.mode not in {"RGB", "RGBA", "L"}:
        image = image.convert("RGB")
    image.save(output, format="PNG")
    return output.getvalue()


def extract_check_images(pdf_bytes: bytes) -> list[bytes]:
    """Return embedded check images as PNG bytes; no PDF or image is persisted."""
    images: list[tuple[int, bytes]] = []
    reader = PdfReader(BytesIO(pdf_bytes))
    for page in reader.pages:
        for item in page.images:
            image = item.image
            width, height = image.size
            if width < 400 or height < 150:
                continue
            images.append((width * height, _image_png(image)))
    return [data for _, data in sorted(images, key=lambda pair: pair[0], reverse=True)]


def extract_check_images_with_text(pdf_bytes: bytes) -> list[tuple[bytes, str]]:
    """Every check-sized image in a PDF, in page order, with the text printed on its page."""
    found: list[tuple[bytes, str]] = []
    reader = PdfReader(BytesIO(pdf_bytes))
    for page in reader.pages:
        text = page.extract_text() or ""
        for item in page.images:
            image = item.image
            width, height = image.size
            if width < 400 or height < 150:
                continue
            found.append((_image_png(image), text))
    return found


def group_check_images(
    images: list[tuple[bytes, str]], per_check: int = 2
) -> list[list[tuple[bytes, str]]]:
    """Split a flat list of images into checks (front/back pairs by default)."""
    per_check = max(1, per_check)
    return [images[i:i + per_check] for i in range(0, len(images), per_check)]


def match_text_to_check(checks: list[dict[str, Any]], text: str) -> int | None:
    """Find the statement check whose check number or amount is printed in ``text``."""
    for number in re.findall(r"Check\s*(?:number|no\.?|#)\s*:?\s*(\d+)", text, flags=re.IGNORECASE):
        hits = [i for i, check in enumerate(checks) if str(check["check_number"]) == number]
        if len(hits) == 1:
            return hits[0]
    for raw in dict.fromkeys(re.findall(r"\$?\s*([\d,]+\.\d{2})", text)):
        try:
            value = _money(raw)
        except ValueError:
            continue
        hits = [i for i, check in enumerate(checks) if abs(float(check["amount"]) - value) < 0.005]
        if len(hits) == 1:
            return hits[0]
    return None


def resolve_check_index(checks: list[dict[str, Any]], image_set: dict[str, Any]) -> int | None:
    """The statement check an image set belongs to: an explicit guess if it has one, else the file name."""
    if "check_index" in image_set:
        return image_set["check_index"]
    return match_check_index(checks, image_set["name"])


def extract_boa_check_image_sets(pdf_bytes: bytes, source_name: str) -> list[dict[str, Any]]:
    """Pair embedded BOA check images with the printed check metadata on each image page."""
    result: list[dict[str, Any]] = []
    reader = PdfReader(BytesIO(pdf_bytes))
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if "CHECK IMAGES" not in text.upper():
            continue
        metadata = re.findall(
            r"Check number:\s*(\d+)\s*[!|]?\s*Amount:\s*\$?([\d,]+\.\d{2})",
            text,
            flags=re.IGNORECASE,
        )
        images: list[bytes] = []
        for item in page.images:
            image = item.image
            width, height = image.size
            if width >= 400 and height >= 150:
                images.append(_image_png(image))
        if not metadata or not images:
            continue
        if len(metadata) == 1:
            number, amount = metadata[0]
            result.append({
                "name": f"{source_name} · Check #{number}",
                "check_number": number,
                "amount": _money(amount),
                "page_number": page_number,
                "images": images,
            })
        else:
            for (number, amount), image in zip(metadata, images):
                result.append({
                    "name": f"{source_name} · Check #{number}",
                    "check_number": number,
                    "amount": _money(amount),
                    "page_number": page_number,
                    "images": [image],
                })
    return result


def match_check_index(checks: list[dict[str, Any]], source_name: str) -> int | None:
    numbers = re.findall(r"\d+(?:\.\d+)?", Path(source_name).stem.replace(",", ""))
    for token in numbers:
        value = float(token)
        amount_matches = [
            index for index, check in enumerate(checks)
            if abs(float(check["amount"]) - value) < 0.005
        ]
        if len(amount_matches) == 1:
            return amount_matches[0]
    for token in numbers:
        for index, check in enumerate(checks):
            if str(check["check_number"]) == token:
                return index
    return None


def suggest_check_index(checks: list[dict[str, Any]], source_name: str) -> int:
    matched = match_check_index(checks, source_name)
    return matched if matched is not None else 0
