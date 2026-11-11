from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


TREATMENTS = (
    "Revenue",
    "Revenue refund",
    "Expense",
    "Expense refund",
    "Transfer",
    "Loan draw",
    "Principal repayment",
    "Loan receivable",
    "Receivable repayment",
    "Excluded",
    "Needs review",
)

ACCOUNT_TYPES = (
    "checking",
    "savings",
    "credit_card",
    "line_of_credit",
    "cash",
    "other",
)

CHECK_TYPES = ("payment", "deposit")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_description(value: str | None) -> str:
    text = (value or "").upper().strip()
    text = re.sub(r"\b(CONF(?:IRMATION)?#?|REFERENCE|REF)\s*[:#-]?\s*[A-Z0-9-]+", " ", text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", text)
    text = re.sub(r"\b\d{7,}\b", " ", text)
    text = re.sub(r"[^A-Z0-9*&/.' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def learned_pattern(description: str) -> str:
    normalized = normalize_description(description)
    return normalized[:180]


def suggested_vendor_pattern(description: str) -> str:
    raw = (description or "").strip()
    ach_match = re.match(r"^(.+?)\s+DES\s*:", raw, flags=re.IGNORECASE)
    if ach_match:
        return normalize_description(ach_match.group(1))[:80]
    zelle_match = re.search(
        r"ZELLE\s+PAYMENT\s+(?:TO|FROM)\s+(.+?)(?:\s+FOR\s+|;|\s+CONF#|$)",
        raw,
        flags=re.IGNORECASE,
    )
    if zelle_match:
        return normalize_description(zelle_match.group(1))[:80]
    normalized = normalize_description(raw)
    stop_markers = (" ID ", " CO ID ", " CCD ", " ACH ", " PAYMENT ID ")
    for marker in stop_markers:
        if marker in normalized:
            normalized = normalized.split(marker, 1)[0]
    return " ".join(normalized.split()[:4])[:80]


def transaction_fingerprint(
    business_id: int,
    account_id: int,
    transaction_date: str,
    source_amount: float,
    description: str,
    source_reference: str | None = None,
) -> str:
    reference = normalize_description(source_reference or "")
    payload = "|".join(
        [
            str(business_id),
            str(account_id),
            transaction_date,
            f"{source_amount:.2f}",
            normalize_description(description),
            reference,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    institution TEXT,
    last4 TEXT,
    opening_balance REAL NOT NULL DEFAULT 0,
    credit_limit REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(business_id, name)
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    default_treatment TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(business_id, name)
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    undone_at TEXT
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    pattern TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'contains',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    treatment TEXT NOT NULL,
    related_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    amount_min REAL,
    amount_max REAL,
    priority INTEGER NOT NULL DEFAULT 100,
    active INTEGER NOT NULL DEFAULT 1,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, account_id, pattern)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    transaction_date TEXT NOT NULL,
    posting_date TEXT,
    description TEXT NOT NULL,
    normalized_description TEXT NOT NULL,
    source_amount REAL NOT NULL,
    signed_amount REAL NOT NULL,
    source_category TEXT,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    treatment TEXT NOT NULL DEFAULT 'Needs review',
    status TEXT NOT NULL DEFAULT 'needs_review',
    related_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    source_file TEXT,
    source_reference TEXT,
    notes TEXT,
    raw_json TEXT,
    import_batch_id INTEGER REFERENCES import_batches(id) ON DELETE CASCADE,
    learned_rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_business_status
ON transactions(business_id, status);
CREATE INDEX IF NOT EXISTS idx_transactions_account_date
ON transactions(account_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_rules_business_active
ON rules(business_id, active, priority);

CREATE TABLE IF NOT EXISTS loan_events (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    loc_account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    principal_amount REAL NOT NULL DEFAULT 0,
    interest_amount REAL NOT NULL DEFAULT 0,
    fee_amount REAL NOT NULL DEFAULT 0,
    linked_transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    match_pattern TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    treatment TEXT NOT NULL,
    rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, name),
    UNIQUE(business_id, match_pattern)
);

CREATE TABLE IF NOT EXISTS check_register (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    bank_name TEXT NOT NULL,
    account_last4 TEXT,
    statement_date TEXT NOT NULL,
    check_number TEXT NOT NULL,
    amount REAL NOT NULL,
    check_type TEXT NOT NULL DEFAULT 'payment',
    written_date TEXT,
    cleared_date TEXT NOT NULL,
    payee TEXT,
    memo TEXT,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    treatment TEXT,
    source_file_name TEXT,
    confirmed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, account_id, check_number, cleared_date, amount)
);

CREATE INDEX IF NOT EXISTS idx_check_register_business_date
ON check_register(business_id, cleared_date);
"""


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(check_register)")}
        if "check_type" not in columns:
            connection.execute(
                "ALTER TABLE check_register ADD COLUMN check_type TEXT NOT NULL DEFAULT 'payment'"
            )


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "business"


def get_or_create_business(connection: sqlite3.Connection, name: str) -> int:
    row = connection.execute("SELECT id FROM businesses WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    slug = slugify(name)
    suffix = 2
    candidate = slug
    while connection.execute("SELECT 1 FROM businesses WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{slug}-{suffix}"
        suffix += 1
    cursor = connection.execute(
        "INSERT INTO businesses(name, slug, created_at) VALUES (?, ?, ?)",
        (name, candidate, utc_now()),
    )
    return int(cursor.lastrowid)


def list_businesses(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute("SELECT * FROM businesses WHERE active = 1 ORDER BY name")]


def get_or_create_account(
    connection: sqlite3.Connection,
    business_id: int,
    name: str,
    account_type: str,
    institution: str | None = None,
    last4: str | None = None,
    opening_balance: float = 0,
    credit_limit: float = 0,
) -> int:
    row = connection.execute(
        "SELECT id FROM accounts WHERE business_id = ? AND name = ?",
        (business_id, name),
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = connection.execute(
        """INSERT INTO accounts(
            business_id, name, account_type, institution, last4,
            opening_balance, credit_limit, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (business_id, name, account_type, institution, last4, opening_balance, credit_limit, utc_now()),
    )
    return int(cursor.lastrowid)


def list_accounts(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM accounts WHERE business_id = ? AND active = 1 ORDER BY account_type, name",
            (business_id,),
        )
    ]


def update_account(
    connection: sqlite3.Connection,
    account_id: int,
    *,
    name: str,
    account_type: str,
    institution: str | None,
    last4: str | None,
    opening_balance: float,
    credit_limit: float,
) -> None:
    connection.execute(
        """UPDATE accounts
           SET name = ?, account_type = ?, institution = ?, last4 = ?,
               opening_balance = ?, credit_limit = ?
           WHERE id = ?""",
        (name, account_type, institution, last4, opening_balance, credit_limit, account_id),
    )


def get_or_create_category(
    connection: sqlite3.Connection,
    business_id: int,
    name: str,
    default_treatment: str,
) -> int:
    row = connection.execute(
        "SELECT id FROM categories WHERE business_id = ? AND name = ?",
        (business_id, name),
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = connection.execute(
        "INSERT INTO categories(business_id, name, default_treatment, created_at) VALUES (?, ?, ?, ?)",
        (business_id, name, default_treatment, utc_now()),
    )
    return int(cursor.lastrowid)


def list_categories(
    connection: sqlite3.Connection,
    business_id: int,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    active_filter = "" if include_inactive else " AND active = 1"
    return [
        dict(row)
        for row in connection.execute(
            f"SELECT * FROM categories WHERE business_id = ?{active_filter} ORDER BY active DESC, name",
            (business_id,),
        )
    ]


def update_category(
    connection: sqlite3.Connection,
    category_id: int,
    *,
    name: str,
    default_treatment: str,
    active: bool,
) -> None:
    connection.execute(
        "UPDATE categories SET name = ?, default_treatment = ?, active = ? WHERE id = ?",
        (name.strip(), default_treatment, 1 if active else 0, category_id),
    )


def update_business(connection: sqlite3.Connection, business_id: int, name: str) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Business name is required")
    connection.execute(
        "UPDATE businesses SET name = ?, slug = ? WHERE id = ?",
        (clean_name, slugify(clean_name), business_id),
    )


def create_import_batch(
    connection: sqlite3.Connection,
    business_id: int,
    account_id: int | None,
    source_name: str,
    source_type: str,
) -> int:
    cursor = connection.execute(
        """INSERT INTO import_batches(
            business_id, account_id, source_name, source_type, created_at
        ) VALUES (?, ?, ?, ?, ?)""",
        (business_id, account_id, source_name, source_type, utc_now()),
    )
    return int(cursor.lastrowid)


def _match_rule(
    connection: sqlite3.Connection,
    business_id: int,
    account_id: int,
    normalized_description: str,
    signed_amount: float,
) -> dict[str, Any] | None:
    rows = connection.execute(
        """SELECT * FROM rules
           WHERE business_id = ? AND active = 1
             AND (account_id = ? OR account_id IS NULL)
             AND (amount_min IS NULL OR ? >= amount_min)
             AND (amount_max IS NULL OR ? <= amount_max)
           ORDER BY (account_id IS NOT NULL) DESC, priority DESC, LENGTH(pattern) DESC, id ASC""",
        (business_id, account_id, signed_amount, signed_amount),
    ).fetchall()
    for row in rows:
        rule = dict(row)
        pattern = rule["pattern"]
        if rule["match_type"] == "exact" and normalized_description == pattern:
            return rule
        if rule["match_type"] == "contains" and pattern in normalized_description:
            return rule
    return None


def insert_transaction(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int,
    transaction_date: str,
    posting_date: str | None,
    description: str,
    source_amount: float,
    signed_amount: float,
    source_category: str | None = None,
    category_id: int | None = None,
    treatment: str = "Needs review",
    status: str = "needs_review",
    related_account_id: int | None = None,
    source_file: str | None = None,
    source_reference: str | None = None,
    notes: str | None = None,
    raw: dict[str, Any] | None = None,
    import_batch_id: int | None = None,
    allow_rules: bool = True,
) -> tuple[int | None, bool, bool]:
    fingerprint = transaction_fingerprint(
        business_id,
        account_id,
        transaction_date,
        source_amount,
        description,
        source_reference,
    )
    existing = connection.execute(
        "SELECT id FROM transactions WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if existing:
        return int(existing["id"]), True, False

    normalized = normalize_description(description)
    learned_rule_id = None
    auto_classified = False
    if allow_rules and treatment == "Needs review":
        rule = _match_rule(connection, business_id, account_id, normalized, signed_amount)
        if rule:
            category_id = rule["category_id"]
            treatment = rule["treatment"]
            related_account_id = rule["related_account_id"]
            status = "auto_classified"
            learned_rule_id = rule["id"]
            auto_classified = True
            connection.execute("UPDATE rules SET hit_count = hit_count + 1 WHERE id = ?", (rule["id"],))

    now = utc_now()
    cursor = connection.execute(
        """INSERT INTO transactions(
            business_id, account_id, transaction_date, posting_date,
            description, normalized_description, source_amount, signed_amount,
            source_category, category_id, treatment, status, related_account_id,
            source_file, source_reference, notes, raw_json, import_batch_id,
            learned_rule_id, fingerprint, reviewed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            business_id,
            account_id,
            transaction_date,
            posting_date,
            description,
            normalized,
            source_amount,
            signed_amount,
            source_category,
            category_id,
            treatment,
            status,
            related_account_id,
            source_file,
            source_reference,
            notes,
            json.dumps(raw or {}, default=str),
            import_batch_id,
            learned_rule_id,
            fingerprint,
            now if status in {"confirmed", "auto_classified"} else None,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid), False, auto_classified


def finish_import_batch(
    connection: sqlite3.Connection,
    batch_id: int,
    imported_count: int,
    duplicate_count: int,
    review_count: int,
) -> None:
    connection.execute(
        """UPDATE import_batches
           SET imported_count = ?, duplicate_count = ?, review_count = ?
           WHERE id = ?""",
        (imported_count, duplicate_count, review_count, batch_id),
    )


def undo_import_batch(connection: sqlite3.Connection, batch_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM transactions WHERE import_batch_id = ?", (batch_id,)
    ).fetchone()
    count = int(row["count"])
    connection.execute("DELETE FROM transactions WHERE import_batch_id = ?", (batch_id,))
    connection.execute("UPDATE import_batches SET undone_at = ? WHERE id = ?", (utc_now(), batch_id))
    return count


def list_import_batches(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT b.*, a.name AS account_name
               FROM import_batches b
               LEFT JOIN accounts a ON a.id = b.account_id
               WHERE b.business_id = ?
               ORDER BY b.id DESC""",
            (business_id,),
        )
    ]


def learn_rule(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int | None,
    pattern: str,
    category_id: int | None,
    treatment: str,
    related_account_id: int | None = None,
    apply_existing: bool = True,
) -> tuple[int, int]:
    pattern = normalize_description(pattern)
    if not pattern:
        raise ValueError("A learning pattern is required")
    now = utc_now()
    existing = connection.execute(
        """SELECT id FROM rules
           WHERE business_id = ? AND account_id IS ? AND pattern = ?""",
        (business_id, account_id, pattern),
    ).fetchone()
    if existing:
        rule_id = int(existing["id"])
        connection.execute(
            """UPDATE rules
               SET category_id = ?, treatment = ?, related_account_id = ?,
                   active = 1, updated_at = ?
               WHERE id = ?""",
            (category_id, treatment, related_account_id, now, rule_id),
        )
    else:
        cursor = connection.execute(
            """INSERT INTO rules(
                business_id, account_id, pattern, category_id, treatment,
                related_account_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (business_id, account_id, pattern, category_id, treatment, related_account_id, now, now),
        )
        rule_id = int(cursor.lastrowid)

    applied = 0
    if apply_existing:
        params: list[Any] = [category_id, treatment, related_account_id, rule_id, now, now, business_id]
        account_filter = ""
        if account_id is not None:
            account_filter = " AND account_id = ?"
            params.append(account_id)
        params.append(f"%{pattern}%")
        cursor = connection.execute(
            f"""UPDATE transactions
                SET category_id = ?, treatment = ?, related_account_id = ?,
                    learned_rule_id = ?, status = 'auto_classified',
                    reviewed_at = ?, updated_at = ?
                WHERE business_id = ? {account_filter}
                  AND status = 'needs_review'
                  AND normalized_description LIKE ?""",
            params,
        )
        applied = cursor.rowcount
        if applied:
            connection.execute("UPDATE rules SET hit_count = hit_count + ? WHERE id = ?", (applied, rule_id))
    return rule_id, applied


def list_vendors(
    connection: sqlite3.Connection,
    business_id: int,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    active_filter = "" if include_inactive else " AND v.active = 1"
    return [
        dict(row)
        for row in connection.execute(
            f"""SELECT v.*, c.name AS category_name, r.hit_count
                FROM vendors v
                LEFT JOIN categories c ON c.id = v.category_id
                LEFT JOIN rules r ON r.id = v.rule_id
                WHERE v.business_id = ?{active_filter}
                ORDER BY v.active DESC, v.name""",
            (business_id,),
        )
    ]


def upsert_vendor(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    name: str,
    match_pattern: str,
    category_id: int | None,
    treatment: str,
    vendor_id: int | None = None,
    active: bool = True,
    apply_existing: bool = True,
) -> tuple[int, int]:
    clean_name = name.strip()
    pattern = normalize_description(match_pattern)
    if not clean_name or not pattern:
        raise ValueError("Vendor name and matching text are required")
    old = None
    if vendor_id is not None:
        old = connection.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    if old is None:
        old = connection.execute(
            "SELECT * FROM vendors WHERE business_id = ? AND (name = ? OR match_pattern = ?)",
            (business_id, clean_name, pattern),
        ).fetchone()
    rule_id, applied = learn_rule(
        connection,
        business_id=business_id,
        account_id=None,
        pattern=pattern,
        category_id=category_id,
        treatment=treatment,
        apply_existing=apply_existing,
    )
    now = utc_now()
    if old:
        vendor_id = int(old["id"])
        if old["rule_id"] and int(old["rule_id"]) != rule_id:
            set_rule_active(connection, int(old["rule_id"]), False)
        connection.execute(
            """UPDATE vendors SET name = ?, match_pattern = ?, category_id = ?,
                   treatment = ?, rule_id = ?, active = ?, updated_at = ? WHERE id = ?""",
            (clean_name, pattern, category_id, treatment, rule_id, 1 if active else 0, now, vendor_id),
        )
    else:
        cursor = connection.execute(
            """INSERT INTO vendors(business_id, name, match_pattern, category_id, treatment,
                   rule_id, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (business_id, clean_name, pattern, category_id, treatment, rule_id,
             1 if active else 0, now, now),
        )
        vendor_id = int(cursor.lastrowid)
    set_rule_active(connection, rule_id, active)
    return int(vendor_id), applied


def set_vendor_active(connection: sqlite3.Connection, vendor_id: int, active: bool) -> None:
    row = connection.execute("SELECT rule_id FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    connection.execute(
        "UPDATE vendors SET active = ?, updated_at = ? WHERE id = ?",
        (1 if active else 0, utc_now(), vendor_id),
    )
    if row and row["rule_id"]:
        set_rule_active(connection, int(row["rule_id"]), active)


def classify_transaction(
    connection: sqlite3.Connection,
    transaction_id: int,
    *,
    category_id: int | None,
    treatment: str,
    related_account_id: int | None = None,
    notes: str | None = None,
    pattern: str | None = None,
    apply_existing: bool = True,
) -> tuple[int, int]:
    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if not transaction:
        raise ValueError("Transaction not found")
    now = utc_now()
    connection.execute(
        """UPDATE transactions
           SET category_id = ?, treatment = ?, related_account_id = ?,
               status = 'confirmed', notes = COALESCE(?, notes),
               reviewed_at = ?, updated_at = ?
           WHERE id = ?""",
        (category_id, treatment, related_account_id, notes, now, now, transaction_id),
    )
    rule_pattern = pattern or learned_pattern(transaction["description"])
    rule_id, applied = learn_rule(
        connection,
        business_id=int(transaction["business_id"]),
        account_id=int(transaction["account_id"]),
        pattern=rule_pattern,
        category_id=category_id,
        treatment=treatment,
        related_account_id=related_account_id,
        apply_existing=apply_existing,
    )
    connection.execute(
        "UPDATE transactions SET learned_rule_id = ? WHERE id = ?", (rule_id, transaction_id)
    )
    return rule_id, applied


def update_transaction_classification(
    connection: sqlite3.Connection,
    transaction_id: int,
    *,
    category_id: int | None,
    treatment: str | None = None,
    related_account_id: int | None = None,
    notes: str | None = None,
) -> None:
    now = utc_now()
    if treatment is None:
        connection.execute(
            """UPDATE transactions SET category_id = ?, related_account_id = ?,
                   notes = COALESCE(?, notes), status = 'confirmed',
                   reviewed_at = ?, updated_at = ? WHERE id = ?""",
            (category_id, related_account_id, notes, now, now, transaction_id),
        )
    else:
        connection.execute(
            """UPDATE transactions SET category_id = ?, treatment = ?, related_account_id = ?,
                   notes = COALESCE(?, notes), status = 'confirmed',
                   reviewed_at = ?, updated_at = ? WHERE id = ?""",
            (category_id, treatment, related_account_id, notes, now, now, transaction_id),
        )


def list_rules(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT r.*, a.name AS account_name, c.name AS category_name,
                      ra.name AS related_account_name
               FROM rules r
               LEFT JOIN accounts a ON a.id = r.account_id
               LEFT JOIN categories c ON c.id = r.category_id
               LEFT JOIN accounts ra ON ra.id = r.related_account_id
               WHERE r.business_id = ?
               ORDER BY r.active DESC, r.priority DESC, r.pattern""",
            (business_id,),
        )
    ]


def set_rule_active(connection: sqlite3.Connection, rule_id: int, active: bool) -> None:
    connection.execute(
        "UPDATE rules SET active = ?, updated_at = ? WHERE id = ?",
        (1 if active else 0, utc_now(), rule_id),
    )


def get_transaction(connection: sqlite3.Connection, transaction_id: int) -> dict[str, Any] | None:
    return _dict(
        connection.execute(
            """SELECT t.*, a.name AS account_name, c.name AS category_name,
                      ra.name AS related_account_name
               FROM transactions t
               JOIN accounts a ON a.id = t.account_id
               LEFT JOIN categories c ON c.id = t.category_id
               LEFT JOIN accounts ra ON ra.id = t.related_account_id
               WHERE t.id = ?""",
            (transaction_id,),
        ).fetchone()
    )


def list_transactions(
    connection: sqlite3.Connection,
    business_id: int,
    *,
    status: str | None = None,
    account_id: int | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    clauses = ["t.business_id = ?"]
    params: list[Any] = [business_id]
    if status:
        clauses.append("t.status = ?")
        params.append(status)
    if account_id:
        clauses.append("t.account_id = ?")
        params.append(account_id)
    params.append(limit)
    return [
        dict(row)
        for row in connection.execute(
            f"""SELECT t.id, t.transaction_date, t.posting_date, a.name AS account,
                       t.description, t.source_amount, t.signed_amount,
                       t.source_category, c.name AS category, t.treatment,
                       t.status, t.source_file, t.source_reference, t.notes
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.transaction_date DESC, t.id DESC
                LIMIT ?""",
            params,
        )
    ]


def dashboard(connection: sqlite3.Connection, business_id: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    business_filter = ""
    if business_id is not None:
        business_filter = "WHERE b.id = ?"
        params = (business_id,)
    rows = connection.execute(
        f"""SELECT b.id AS business_id, b.name AS business,
            COUNT(t.id) AS transactions,
            SUM(CASE WHEN t.status = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
            COALESCE(SUM(CASE
                WHEN t.treatment IN ('Revenue', 'Revenue refund') THEN t.signed_amount
                ELSE 0 END), 0) AS revenue,
            COALESCE(SUM(CASE
                WHEN t.treatment = 'Expense' THEN ABS(t.signed_amount)
                WHEN t.treatment = 'Expense refund' THEN -ABS(t.signed_amount)
                ELSE 0 END), 0) AS expense,
            MAX(t.transaction_date) AS latest_transaction
            FROM businesses b
            LEFT JOIN transactions t ON t.business_id = b.id
            {business_filter}
            GROUP BY b.id, b.name
            ORDER BY b.name""",
        params,
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["net"] = float(item["revenue"] or 0) - float(item["expense"] or 0)
        item["loc_balance"] = total_loc_balance(connection, int(item["business_id"]))
        result.append(item)
    return result


def account_summaries(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    accounts = list_accounts(connection, business_id)
    result = []
    for account in accounts:
        movement = connection.execute(
            "SELECT COALESCE(SUM(signed_amount), 0) AS value FROM transactions WHERE account_id = ?",
            (account["id"],),
        ).fetchone()["value"]
        if account["account_type"] == "line_of_credit":
            balance = loc_balance(connection, int(account["id"]))
        elif account["account_type"] == "credit_card":
            balance = -float(movement or 0)
        else:
            balance = float(account["opening_balance"] or 0) + float(movement or 0)
        result.append({**account, "movement": float(movement or 0), "balance": balance})
    return result


def add_loan_event(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    loc_account_id: int,
    event_date: str,
    event_type: str,
    amount: float,
    interest_amount: float = 0,
    fee_amount: float = 0,
    linked_transaction_id: int | None = None,
    notes: str | None = None,
) -> int:
    principal_amount = amount if event_type in {"draw", "principal_payment", "adjustment"} else 0
    cursor = connection.execute(
        """INSERT INTO loan_events(
            business_id, loc_account_id, event_date, event_type,
            principal_amount, interest_amount, fee_amount,
            linked_transaction_id, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            business_id,
            loc_account_id,
            event_date,
            event_type,
            principal_amount,
            interest_amount,
            fee_amount,
            linked_transaction_id,
            notes,
            utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def list_loan_events(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT e.*, a.name AS loc_account
               FROM loan_events e
               JOIN accounts a ON a.id = e.loc_account_id
               WHERE e.business_id = ?
               ORDER BY e.event_date DESC, e.id DESC""",
            (business_id,),
        )
    ]


def loc_balance(connection: sqlite3.Connection, account_id: int) -> float:
    account = connection.execute(
        "SELECT opening_balance FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if not account:
        return 0.0
    events = connection.execute(
        """SELECT event_type, principal_amount
           FROM loan_events WHERE loc_account_id = ?""",
        (account_id,),
    ).fetchall()
    balance = float(account["opening_balance"] or 0)
    for event in events:
        amount = float(event["principal_amount"] or 0)
        if event["event_type"] == "draw":
            balance += amount
        elif event["event_type"] == "principal_payment":
            balance -= amount
        elif event["event_type"] == "adjustment":
            balance += amount
    return balance


def total_loc_balance(connection: sqlite3.Connection, business_id: int) -> float:
    rows = connection.execute(
        "SELECT id FROM accounts WHERE business_id = ? AND account_type = 'line_of_credit' AND active = 1",
        (business_id,),
    ).fetchall()
    return sum(loc_balance(connection, int(row["id"])) for row in rows)


def category_summary(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT c.name AS category, c.default_treatment,
                COUNT(t.id) AS transactions,
                COALESCE(SUM(CASE WHEN t.treatment IN ('Revenue', 'Revenue refund') THEN t.signed_amount ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE
                    WHEN t.treatment = 'Expense' THEN ABS(t.signed_amount)
                    WHEN t.treatment = 'Expense refund' THEN -ABS(t.signed_amount)
                    ELSE 0 END), 0) AS expense
               FROM categories c
               LEFT JOIN transactions t ON t.category_id = c.id
               WHERE c.business_id = ? AND c.active = 1
               GROUP BY c.id, c.name, c.default_treatment
               ORDER BY c.name""",
            (business_id,),
        )
    ]


def get_setting(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, value, utc_now()),
    )


def find_check_transaction_candidates(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int,
    amount: float,
    cleared_date: str,
    check_type: str | None = None,
    day_window: int = 10,
) -> list[dict[str, Any]]:
    if check_type is not None and check_type not in CHECK_TYPES:
        raise ValueError(f"Unsupported check type: {check_type}")
    return [
        dict(row)
        for row in connection.execute(
            """SELECT t.id, t.transaction_date, t.description, t.signed_amount,
                      c.name AS category, t.treatment, t.status
               FROM transactions t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.business_id = ? AND t.account_id = ?
                 AND ABS(ABS(t.signed_amount) - ?) < 0.005
                 AND ABS(julianday(t.transaction_date) - julianday(?)) <= ?
                 AND (? IS NULL
                      OR (? = 'deposit' AND t.signed_amount > 0)
                      OR (? = 'payment' AND t.signed_amount < 0))
               ORDER BY ABS(julianday(t.transaction_date) - julianday(?)), t.id""",
            (business_id, account_id, amount, cleared_date, day_window,
             check_type, check_type, check_type, cleared_date),
        )
    ]


def confirm_check(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int,
    transaction_id: int | None,
    bank_name: str,
    account_last4: str,
    statement_date: str,
    check_number: str,
    amount: float,
    written_date: str | None,
    cleared_date: str,
    payee: str,
    memo: str,
    category_id: int | None,
    treatment: str | None,
    source_file_name: str,
    check_type: str = "payment",
) -> int:
    if check_type not in CHECK_TYPES:
        raise ValueError(f"Unsupported check type: {check_type}")
    if transaction_id:
        matched = connection.execute(
            "SELECT signed_amount FROM transactions WHERE id=? AND business_id=? AND account_id=?",
            (transaction_id, business_id, account_id),
        ).fetchone()
        if matched is None:
            raise ValueError("The selected transaction does not belong to this business and account.")
        signed_amount = float(matched["signed_amount"])
        if (check_type == "deposit" and signed_amount <= 0) or (check_type == "payment" and signed_amount >= 0):
            raise ValueError("The selected transaction direction does not match the check type.")
    now = utc_now()
    cursor = connection.execute(
        """INSERT INTO check_register(
            business_id, account_id, transaction_id, bank_name, account_last4,
            statement_date, check_number, amount, written_date, cleared_date,
            check_type, payee, memo, category_id, treatment, source_file_name,
            confirmed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(business_id, account_id, check_number, cleared_date, amount)
        DO UPDATE SET transaction_id=excluded.transaction_id, bank_name=excluded.bank_name,
            account_last4=excluded.account_last4, statement_date=excluded.statement_date,
            written_date=excluded.written_date, check_type=excluded.check_type,
            payee=excluded.payee, memo=excluded.memo,
            category_id=excluded.category_id, treatment=excluded.treatment,
            source_file_name=excluded.source_file_name, confirmed_at=excluded.confirmed_at,
            updated_at=excluded.updated_at""",
        (business_id, account_id, transaction_id, bank_name, account_last4,
         statement_date, check_number, amount, written_date, cleared_date,
         check_type, payee.strip(), memo.strip(), category_id, treatment, source_file_name,
         now, now, now),
    )
    if transaction_id and treatment:
        update_transaction_classification(
            connection, transaction_id, category_id=category_id, treatment=treatment,
            notes=f"Check #{check_number}: {payee.strip()}" + (f" - {memo.strip()}" if memo.strip() else ""),
        )
    if cursor.lastrowid:
        return int(cursor.lastrowid)
    row = connection.execute(
        """SELECT id FROM check_register WHERE business_id=? AND account_id=?
           AND check_number=? AND cleared_date=? AND amount=?""",
        (business_id, account_id, check_number, cleared_date, amount),
    ).fetchone()
    return int(row["id"])


def list_check_register(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT r.id, r.account_id, r.statement_date, r.cleared_date, r.written_date, r.check_number, r.amount,
                      r.check_type,
                      r.payee, r.memo, r.bank_name, a.name AS account,
                      r.category_id, c.name AS category, r.treatment, r.transaction_id,
                      r.source_file_name, r.confirmed_at
               FROM check_register r
               JOIN accounts a ON a.id = r.account_id
               LEFT JOIN categories c ON c.id = r.category_id
               WHERE r.business_id = ?
               ORDER BY r.cleared_date DESC, CAST(r.check_number AS INTEGER) DESC""",
            (business_id,),
        )
    ]


def delete_check_register_entry(
    connection: sqlite3.Connection, *, business_id: int, check_id: int
) -> bool:
    cursor = connection.execute(
        "DELETE FROM check_register WHERE id = ? AND business_id = ?",
        (check_id, business_id),
    )
    return cursor.rowcount > 0


def list_loan_receivables(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Balances owed to the business, by counterparty (loans made less repayments received).

    Counterparty comes from the check register payee. Bank transactions classified
    as a receivable but not linked to a register entry are grouped separately.
    """
    totals: dict[str, dict[str, float]] = {}

    def add(name: str, treatment: str, amount: float) -> None:
        row = totals.setdefault(name, {"lent": 0.0, "repaid": 0.0})
        row["lent" if treatment == "Loan receivable" else "repaid"] += abs(float(amount))

    for row in connection.execute(
        """SELECT payee, treatment, amount FROM check_register
           WHERE business_id = ? AND treatment IN ('Loan receivable', 'Receivable repayment')""",
        (business_id,),
    ):
        add((row["payee"] or "").strip() or "(No counterparty recorded)", row["treatment"], row["amount"])
    for row in connection.execute(
        """SELECT t.treatment, t.signed_amount FROM transactions t
           WHERE t.business_id = ? AND t.treatment IN ('Loan receivable', 'Receivable repayment')
             AND NOT EXISTS (SELECT 1 FROM check_register r WHERE r.transaction_id = t.id)""",
        (business_id,),
    ):
        add("(Bank transactions without a counterparty)", row["treatment"], row["signed_amount"])
    return [
        {"counterparty": name, "lent": round(v["lent"], 2), "repaid": round(v["repaid"], 2),
         "balance_owed": round(v["lent"] - v["repaid"], 2)}
        for name, v in sorted(totals.items())
    ]
