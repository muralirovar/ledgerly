from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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
    "Owner contribution",
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
LOAN_TREATMENTS = ("Loan draw", "Principal repayment", "Loan receivable", "Receivable repayment")
LOAN_ROLES = {
    "Loan draw": "Borrowed from",
    "Principal repayment": "Repaid to",
    "Loan receivable": "Lent to",
    "Receivable repayment": "Repaid by",
}


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
    counterparty TEXT,
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

CREATE TABLE IF NOT EXISTS statement_log (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    bank_name TEXT NOT NULL,
    account_last4 TEXT,
    statement_date TEXT NOT NULL,
    statement_file_name TEXT,
    statement_check_total REAL NOT NULL DEFAULT 0,
    checks_listed INTEGER NOT NULL DEFAULT 0,
    checks_mapped INTEGER NOT NULL DEFAULT 0,
    mapped_total REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    first_logged_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, account_id, statement_date)
);

CREATE TABLE IF NOT EXISTS statement_log_checks (
    id INTEGER PRIMARY KEY,
    log_id INTEGER NOT NULL REFERENCES statement_log(id) ON DELETE CASCADE,
    check_number TEXT NOT NULL,
    cleared_date TEXT NOT NULL,
    amount REAL NOT NULL,
    reconciled INTEGER NOT NULL DEFAULT 0,
    check_type TEXT,
    payee TEXT,
    treatment TEXT,
    transaction_id INTEGER,
    check_image_file TEXT
);
"""


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(check_register)")}
        transaction_columns = {row["name"] for row in connection.execute("PRAGMA table_info(transactions)")}
        if "counterparty" not in transaction_columns:
            connection.execute("ALTER TABLE transactions ADD COLUMN counterparty TEXT")
            connection.execute(
                """UPDATE transactions SET counterparty = (
                       SELECT r.payee FROM check_register r
                       WHERE r.transaction_id = transactions.id AND TRIM(COALESCE(r.payee, '')) <> ''
                       ORDER BY r.id LIMIT 1)
                   WHERE counterparty IS NULL""")
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


def set_account_last4(connection: sqlite3.Connection, account_id: int, last4: str) -> None:
    connection.execute("UPDATE accounts SET last4 = ? WHERE id = ?", (last4.strip()[-4:], account_id))


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
                       t.counterparty, t.status, t.source_file, t.source_reference, t.notes
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


def _check_number_in(description: str, check_number: str) -> bool:
    """True when the description names this check, e.g. 'Check #147' or 'CHECK 0147'."""
    number = str(check_number).strip().lstrip("0")
    if not number.isdigit():
        return False
    return bool(re.search(rf"(?<!\d)0*{re.escape(number)}(?!\d)", description or "")) and bool(
        re.search(r"chec?k|chk|ck", description or "", flags=re.IGNORECASE))


def find_check_transaction_candidates(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int,
    amount: float,
    cleared_date: str,
    check_type: str | None = None,
    check_number: str | None = None,
    day_window: int = 10,
) -> list[dict[str, Any]]:
    """Bank transactions that could be this check; check-number matches come first."""
    if check_type is not None and check_type not in CHECK_TYPES:
        raise ValueError(f"Unsupported check type: {check_type}")
    rows = [
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
    for row in rows:
        row["number_match"] = bool(check_number) and _check_number_in(row["description"], str(check_number))
    rows.sort(key=lambda row: not row["number_match"])  # stable: keeps date-distance order
    return rows


def reset_transaction_review(connection: sqlite3.Connection, transaction_id: int) -> None:
    """Return a bank transaction to the review queue (used when a check link is removed).

    A deposit can hold several checks, so nothing is reset while another register entry still uses it.
    """
    if connection.execute(
        "SELECT 1 FROM check_register WHERE transaction_id = ? LIMIT 1", (transaction_id,)
    ).fetchone():
        return
    now = utc_now()
    connection.execute(
        """UPDATE transactions SET category_id = NULL, treatment = 'Needs review',
               status = 'needs_review', reviewed_at = NULL, updated_at = ? WHERE id = ?""",
        (now, transaction_id),
    )


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
    previous = connection.execute(
        """SELECT transaction_id FROM check_register WHERE business_id=? AND account_id=?
           AND check_number=? AND cleared_date=? AND amount=?""",
        (business_id, account_id, check_number, cleared_date, amount),
    ).fetchone()
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
    if previous and previous["transaction_id"] and previous["transaction_id"] != transaction_id:
        reset_transaction_review(connection, int(previous["transaction_id"]))
    if transaction_id and payee.strip():
        connection.execute(
            "UPDATE transactions SET counterparty = ? WHERE id = ?", (payee.strip(), transaction_id))
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
    connection: sqlite3.Connection, *, business_id: int, check_id: int,
    reset_transaction: bool = False,
) -> bool:
    row = connection.execute(
        "SELECT transaction_id FROM check_register WHERE id = ? AND business_id = ?",
        (check_id, business_id),
    ).fetchone()
    if row is None:
        return False
    connection.execute(
        "DELETE FROM check_register WHERE id = ? AND business_id = ?", (check_id, business_id))
    if reset_transaction and row["transaction_id"]:
        reset_transaction_review(connection, int(row["transaction_id"]))
    return True


def _payee_key(name: str, loose: bool = True) -> str:
    """Comparison key for a counterparty name. Loose also ignores LLC/Inc-style suffixes."""
    key = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    if loose:
        key = re.sub(r"\b(llc|l l c|inc|incorporated|corp|corporation|co|ltd|llp)\b", " ", key)
    return " ".join(key.split())


def known_parties(connection: sqlite3.Connection, business_id: int) -> list[str]:
    """Every counterparty already on record (checks and transactions), one spelling each, A to Z."""
    best: dict[str, str] = {}
    for row in connection.execute(
        """SELECT payee AS name FROM check_register WHERE business_id = ? AND TRIM(COALESCE(payee,'')) <> ''
           UNION SELECT counterparty FROM transactions WHERE business_id = ? AND TRIM(COALESCE(counterparty,'')) <> ''""",
        (business_id, business_id)):
        name = row["name"].strip()
        key = _payee_key(name)
        if key not in best or len(name) > len(best[key]):
            best[key] = name
    return sorted(best.values(), key=str.lower)


def list_parties(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Every counterparty on checks and bank transactions, with activity and loan balances.

    Spellings that differ only by case, punctuation or an LLC/Inc-style suffix are one party.
    Check-register amounts count only when the check is not already tied to a bank transaction.
    """
    parties: dict[str, dict[str, Any]] = {}

    def entry(name: str) -> dict[str, Any]:
        key = _payee_key(name)
        item = parties.setdefault(key, {
            "spellings": {}, "transactions": 0, "checks": 0, "money_in": 0.0, "money_out": 0.0,
            "lent": 0.0, "lent_repaid": 0.0, "borrowed": 0.0, "borrowed_repaid": 0.0, "last_date": ""})
        item["spellings"][name] = item["spellings"].get(name, 0) + 1
        return item

    for row in connection.execute(
        """SELECT counterparty, signed_amount, treatment, transaction_date FROM transactions
           WHERE business_id = ? AND TRIM(COALESCE(counterparty, '')) <> ''""", (business_id,)):
        item = entry(row["counterparty"].strip())
        amount = float(row["signed_amount"])
        item["transactions"] += 1
        item["money_in" if amount > 0 else "money_out"] += abs(amount)
        item["last_date"] = max(item["last_date"], row["transaction_date"])
        treatment = row["treatment"]
        if treatment == "Loan receivable":
            item["lent"] += abs(amount)
        elif treatment == "Receivable repayment":
            item["lent_repaid"] += abs(amount)
        elif treatment == "Loan draw":
            item["borrowed"] += abs(amount)
        elif treatment == "Principal repayment":
            item["borrowed_repaid"] += abs(amount)
    for row in connection.execute(
        """SELECT payee, amount, check_type, treatment, cleared_date, transaction_id FROM check_register
           WHERE business_id = ? AND TRIM(COALESCE(payee, '')) <> ''""", (business_id,)):
        item = entry(row["payee"].strip())
        item["checks"] += 1
        item["last_date"] = max(item["last_date"], row["cleared_date"] or "")
        if row["transaction_id"] is None:
            amount = float(row["amount"])
            item["money_in" if row["check_type"] == "deposit" else "money_out"] += amount
            treatment = row["treatment"]
            if treatment == "Loan receivable":
                item["lent"] += amount
            elif treatment == "Receivable repayment":
                item["lent_repaid"] += amount
            elif treatment == "Loan draw":
                item["borrowed"] += amount
            elif treatment == "Principal repayment":
                item["borrowed_repaid"] += amount
    result = []
    for item in parties.values():
        spellings = sorted(item["spellings"], key=lambda n: (-len(n), n))
        result.append({
            "party": spellings[0], "spellings": spellings, "transactions": item["transactions"],
            "checks": item["checks"], "money_in": round(item["money_in"], 2),
            "money_out": round(item["money_out"], 2),
            "owed_to_us": round(item["lent"] - item["lent_repaid"], 2),
            "we_owe": round(item["borrowed"] - item["borrowed_repaid"], 2),
            "last_activity": item["last_date"]})
    return sorted(result, key=lambda r: r["party"].lower())


def rename_party(
    connection: sqlite3.Connection, *, business_id: int, old_names: list[str], new_name: str,
) -> dict[str, int]:
    """Rename or merge parties everywhere: bank transactions, check register and the statement log."""
    new_name = " ".join((new_name or "").split())
    if not new_name:
        raise ValueError("Enter the name to use.")
    olds = [n for n in dict.fromkeys(old_names) if n]
    if not olds:
        raise ValueError("Select at least one party.")
    now = utc_now()
    counts = {"transactions": 0, "checks": 0}
    for old in olds:
        counts["transactions"] += connection.execute(
            "UPDATE transactions SET counterparty = ?, updated_at = ? WHERE business_id = ? AND counterparty = ?",
            (new_name, now, business_id, old)).rowcount
        counts["checks"] += connection.execute(
            "UPDATE check_register SET payee = ?, updated_at = ? WHERE business_id = ? AND payee = ?",
            (new_name, now, business_id, old)).rowcount
        connection.execute(
            """UPDATE statement_log_checks SET payee = ? WHERE payee = ? AND log_id IN
               (SELECT id FROM statement_log WHERE business_id = ?)""", (new_name, old, business_id))
    return counts


def party_activity(
    connection: sqlite3.Connection, business_id: int, names: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Bank transactions and checks recorded under the given spellings of a party."""
    marks = ",".join("?" for _ in names) or "''"
    transactions = [dict(r) for r in connection.execute(
        f"""SELECT t.id, t.transaction_date, a.name AS account, t.description, t.signed_amount, t.treatment
            FROM transactions t JOIN accounts a ON a.id = t.account_id
            WHERE t.business_id = ? AND t.counterparty IN ({marks})
            ORDER BY t.transaction_date DESC, t.id DESC""", [business_id, *names])]
    checks = [dict(r) for r in connection.execute(
        f"""SELECT r.cleared_date, r.check_number, r.check_type, r.amount, a.name AS account, r.treatment, r.memo
            FROM check_register r JOIN accounts a ON a.id = r.account_id
            WHERE r.business_id = ? AND r.payee IN ({marks})
            ORDER BY r.cleared_date DESC, r.id DESC""", [business_id, *names])]
    return {"transactions": transactions, "checks": checks}


def payee_history(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Distinct counterparties from the register with their most recent category/treatment/memo."""
    seen: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        """SELECT r.payee, r.memo, r.treatment, r.check_type, c.name AS category, r.cleared_date
           FROM check_register r LEFT JOIN categories c ON c.id = r.category_id
           WHERE r.business_id = ? AND TRIM(COALESCE(r.payee, '')) <> ''
           ORDER BY r.cleared_date DESC, r.id DESC""",
        (business_id,),
    ):
        key = _payee_key(row["payee"])
        if key and key not in seen:
            seen[key] = {"payee": row["payee"].strip(), "memo": row["memo"] or "",
                         "treatment": row["treatment"], "category": row["category"],
                         "check_type": row["check_type"]}
    return sorted(seen.values(), key=lambda item: item["payee"].lower())


def canonical_payee(connection: sqlite3.Connection, business_id: int, payee: str, loose: bool = True) -> str:
    """Existing spelling of a counterparty that matches ignoring case and punctuation.

    With ``loose`` (the default) LLC/Inc-style suffixes are ignored too.
    """
    key = _payee_key(payee, loose)
    for item in payee_history(connection, business_id):
        if _payee_key(item["payee"], loose) == key:
            return item["payee"]
    for row in connection.execute(
        """SELECT DISTINCT counterparty FROM transactions
           WHERE business_id = ? AND TRIM(COALESCE(counterparty, '')) <> ''""", (business_id,)):
        if _payee_key(row["counterparty"], loose) == key:
            return row["counterparty"].strip()
    return payee.strip()


def set_transaction_counterparty(
    connection: sqlite3.Connection, *, business_id: int, transaction_id: int, counterparty: str
) -> str:
    """Set who a transaction was paid to / received from (the lender or borrower for loans).

    Reuses the existing spelling when only case or punctuation differs (an explicit change of
    suffix, such as Corp to Inc, is respected), and keeps a single
    linked check-register entry in step. Returns the name that was stored.
    """
    name = canonical_payee(connection, business_id, counterparty, loose=False) if counterparty.strip() else ""
    cursor = connection.execute(
        "UPDATE transactions SET counterparty = ?, updated_at = ? WHERE id = ? AND business_id = ?",
        (name or None, utc_now(), transaction_id, business_id))
    if cursor.rowcount == 0:
        raise ValueError("Transaction not found.")
    linked = connection.execute(
        "SELECT id FROM check_register WHERE transaction_id = ?", (transaction_id,)).fetchall()
    if len(linked) == 1:
        connection.execute("UPDATE check_register SET payee = ?, updated_at = ? WHERE id = ?",
                           (name, utc_now(), linked[0]["id"]))
    return name


def list_loan_receivables(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Balances owed to the business, by counterparty (loans made less repayments received).

    Counterparty comes from the check register payee. Bank transactions classified
    as a receivable but not linked to a register entry are grouped separately.
    """
    totals: dict[str, dict[str, float]] = {}
    display: dict[str, str] = {}

    def add(name: str, treatment: str, amount: float) -> None:
        key = _payee_key(name) or name
        if len(name) > len(display.get(key, "")):  # prefer the fuller spelling, e.g. with "LLC"
            display[key] = name
        row = totals.setdefault(key, {"lent": 0.0, "repaid": 0.0})
        row["lent" if treatment == "Loan receivable" else "repaid"] += abs(float(amount))

    for row in connection.execute(
        """SELECT payee, treatment, amount FROM check_register
           WHERE business_id = ? AND treatment IN ('Loan receivable', 'Receivable repayment')""",
        (business_id,),
    ):
        add((row["payee"] or "").strip() or "(No counterparty recorded)", row["treatment"], row["amount"])
    for row in connection.execute(
        """SELECT t.treatment, t.signed_amount, t.counterparty FROM transactions t
           WHERE t.business_id = ? AND t.treatment IN ('Loan receivable', 'Receivable repayment')
             AND NOT EXISTS (SELECT 1 FROM check_register r WHERE r.transaction_id = t.id)""",
        (business_id,),
    ):
        add((row["counterparty"] or "").strip() or "(Bank transactions without a counterparty)",
            row["treatment"], row["signed_amount"])
    return [
        {"counterparty": display[key], "lent": round(v["lent"], 2), "repaid": round(v["repaid"], 2),
         "balance_owed": round(v["lent"] - v["repaid"], 2)}
        for key, v in sorted(totals.items(), key=lambda item: display[item[0]].lower())
    ]


def log_statement_reconciliation(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int,
    bank_name: str,
    account_last4: str,
    statement_date: str,
    statement_file_name: str | None,
    statement_check_total: float,
    statement_checks: list[dict[str, Any]],
) -> int:
    """Record which statement was reconciled and the state of each check on it.

    One log entry exists per account and statement date; saving again refreshes the snapshot
    (so progress is captured as checks are confirmed) while keeping the first-logged time.
    """
    now = utc_now()
    register = {
        (str(row["check_number"]), row["cleared_date"], round(float(row["amount"]), 2)): dict(row)
        for row in connection.execute(
            "SELECT * FROM check_register WHERE business_id = ? AND account_id = ?",
            (business_id, account_id),
        )
    }
    lines = []
    for item in statement_checks:
        key = (str(item["check_number"]), item["cleared_date"], round(float(item["amount"]), 2))
        entry = register.get(key)
        lines.append((item, entry))
    mapped = [(item, entry) for item, entry in lines if entry]
    mapped_total = round(sum(float(item["amount"]) for item, _ in mapped), 2)
    complete = bool(lines) and len(mapped) == len(lines)
    status = "Reconciled" if complete else ("In progress" if mapped else "Not started")
    existing = connection.execute(
        "SELECT id, first_logged_at FROM statement_log WHERE business_id=? AND account_id=? AND statement_date=?",
        (business_id, account_id, statement_date),
    ).fetchone()
    if existing:
        log_id = int(existing["id"])
        connection.execute(
            """UPDATE statement_log SET bank_name=?, account_last4=?, statement_file_name=COALESCE(?, statement_file_name),
                   statement_check_total=?, checks_listed=?, checks_mapped=?, mapped_total=?, status=?, updated_at=?
               WHERE id=?""",
            (bank_name, account_last4, statement_file_name, statement_check_total, len(lines),
             len(mapped), mapped_total, status, now, log_id),
        )
        connection.execute("DELETE FROM statement_log_checks WHERE log_id = ?", (log_id,))
    else:
        log_id = int(connection.execute(
            """INSERT INTO statement_log(business_id, account_id, bank_name, account_last4, statement_date,
                   statement_file_name, statement_check_total, checks_listed, checks_mapped, mapped_total,
                   status, first_logged_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (business_id, account_id, bank_name, account_last4, statement_date, statement_file_name,
             statement_check_total, len(lines), len(mapped), mapped_total, status, now, now),
        ).lastrowid)
    connection.executemany(
        """INSERT INTO statement_log_checks(log_id, check_number, cleared_date, amount, reconciled,
               check_type, payee, treatment, transaction_id, check_image_file)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(log_id, str(item["check_number"]), item["cleared_date"], float(item["amount"]),
          1 if entry else 0, entry and entry["check_type"], entry and entry["payee"],
          entry and entry["treatment"], entry and entry["transaction_id"], entry and entry["source_file_name"])
         for item, entry in lines],
    )
    return log_id


def ensure_deposit_log_entries(connection: sqlite3.Connection, business_id: int) -> None:
    """Make sure every deposited check belongs to a statement in the log.

    A deposit is filed under the first logged statement of its account that ends on or after
    the deposit date; if there is none, a deposits-only entry is created for that month.
    """
    for row in connection.execute(
        """SELECT r.account_id, r.cleared_date, r.statement_date, r.bank_name, r.account_last4
           FROM check_register r WHERE r.business_id = ? AND r.check_type = 'deposit'""",
        (business_id,)).fetchall():
        covered = connection.execute(
            "SELECT 1 FROM statement_log WHERE business_id=? AND account_id=? AND statement_date >= ? LIMIT 1",
            (business_id, row["account_id"], row["cleared_date"])).fetchone()
        if covered:
            continue
        now = utc_now()
        connection.execute(
            """INSERT OR IGNORE INTO statement_log(business_id, account_id, bank_name, account_last4, statement_date,
                   statement_file_name, statement_check_total, checks_listed, checks_mapped, mapped_total,
                   status, first_logged_at, updated_at)
               VALUES (?, ?, ?, ?, ?, NULL, 0, 0, 0, 0, 'Deposits only', ?, ?)""",
            (business_id, row["account_id"], row["bank_name"] or "", row["account_last4"] or "",
             row["statement_date"], now, now))


def _deposits_by_log(connection: sqlite3.Connection, business_id: int) -> dict[int, list[dict[str, Any]]]:
    """Deposited checks grouped under the statement (log entry) that covers their date."""
    logs: dict[int, list[tuple[str, int]]] = {}
    for row in connection.execute(
        "SELECT id, account_id, statement_date FROM statement_log WHERE business_id = ? ORDER BY statement_date",
        (business_id,)):
        logs.setdefault(int(row["account_id"]), []).append((row["statement_date"], int(row["id"])))
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in connection.execute(
        """SELECT * FROM check_register WHERE business_id = ? AND check_type = 'deposit'
           ORDER BY cleared_date, id""", (business_id,)):
        for statement_date, log_id in logs.get(int(row["account_id"]), []):
            if statement_date >= row["cleared_date"]:
                grouped.setdefault(log_id, []).append(dict(row))
                break
    return grouped


def list_statement_log(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    ensure_deposit_log_entries(connection, business_id)
    deposits = _deposits_by_log(connection, business_id)
    rows = [dict(row) for row in connection.execute(
        """SELECT l.id, l.statement_file_name, l.bank_name, a.name AS account, l.account_last4,
                  l.statement_date, l.checks_listed, l.checks_mapped, l.statement_check_total,
                  l.mapped_total, l.status, l.first_logged_at, l.updated_at
           FROM statement_log l JOIN accounts a ON a.id = l.account_id
           WHERE l.business_id = ? ORDER BY l.statement_date DESC, l.id DESC""",
        (business_id,))]
    for row in rows:
        mine = deposits.get(int(row["id"]), [])
        row["deposits_reconciled"] = len(mine)
        row["deposit_total"] = round(sum(float(item["amount"]) for item in mine), 2)
    return rows


def statement_log_rows(connection: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """One row per statement check and per deposited check, statement details repeated: ready for CSV/Excel archiving."""
    ensure_deposit_log_entries(connection, business_id)
    rows = [dict(row) for row in connection.execute(
        """SELECT l.statement_file_name AS statement_file, l.bank_name AS bank, a.name AS account,
                  l.account_last4, l.statement_date, l.status AS statement_status,
                  k.check_number, k.cleared_date, k.amount,
                  CASE k.reconciled WHEN 1 THEN 'Yes' ELSE 'No' END AS reconciled,
                  k.check_type AS direction, k.payee AS counterparty, k.treatment,
                  k.transaction_id, k.check_image_file, l.updated_at AS logged_at
           FROM statement_log l
           JOIN accounts a ON a.id = l.account_id
           JOIN statement_log_checks k ON k.log_id = l.id
           WHERE l.business_id = ?
           ORDER BY l.statement_date DESC, l.id DESC, CAST(k.check_number AS INTEGER)""",
        (business_id,))]
    deposits = _deposits_by_log(connection, business_id)
    if deposits:
        meta = {int(r["id"]): dict(r) for r in connection.execute(
            """SELECT l.id, l.statement_file_name, l.bank_name, a.name AS account, l.account_last4,
                      l.statement_date, l.status, l.updated_at
               FROM statement_log l JOIN accounts a ON a.id = l.account_id WHERE l.business_id = ?""",
            (business_id,))}
        for log_id, items in deposits.items():
            info = meta[log_id]
            for item in items:
                rows.append({
                    "statement_file": info["statement_file_name"], "bank": info["bank_name"],
                    "account": info["account"], "account_last4": info["account_last4"],
                    "statement_date": info["statement_date"], "statement_status": info["status"],
                    "check_number": item["check_number"], "cleared_date": item["cleared_date"],
                    "amount": item["amount"], "reconciled": "Yes", "direction": "deposit",
                    "counterparty": item["payee"], "treatment": item["treatment"],
                    "transaction_id": item["transaction_id"], "check_image_file": item["source_file_name"],
                    "logged_at": info["updated_at"]})
        rows.sort(key=lambda r: (str(r["statement_date"]), str(r["account"]), str(r["direction"] or ""),
                                 str(r["cleared_date"])), reverse=True)
    return rows


_CHECK_DEPOSIT_HINT = re.compile(
    r"counter\s*credit|deposit|check|chk|remote|rdc|lockbox|cash\s*letter|\bcredit\b", re.IGNORECASE)
_NOT_A_CHECK = re.compile(r"\bACH\b|WIRE|ZELLE|\bCTX\b|\bPPD\b|\bCCD\b|DES:|INTEREST|ACCTVERIFY|TRANSFER", re.IGNORECASE)


def looks_like_check_deposit(description: str) -> bool:
    text = description or ""
    return bool(_CHECK_DEPOSIT_HINT.search(text)) and not _NOT_A_CHECK.search(text)


_DEPOSIT_KINDS = (
    ("Cash / ATM", re.compile(r"\bATM\b|\bCASH\b|BRANCH\s+DEP|COUNTER\s+DEP", re.I)),
    ("Mobile / check", re.compile(r"MOBILE|REMOTE|CHECK\s+DEP|CHK\s+DEP|\bCHECK\b", re.I)),
    ("Wire / ACH", re.compile(r"\bWIRE\b|\bACH\b|ZELLE|TRANSFER|XFER|\bDEPOSIT\s+FROM\b", re.I)),
    ("Other deposit", re.compile(r"DEPOSIT", re.I)),
)


def deposit_kind(description: str) -> str:
    """How a credit reached the account, judged from its bank description."""
    for kind, pattern in _DEPOSIT_KINDS:
        if pattern.search(description or ""):
            return kind
    return "Other credit"


def list_deposits(
    connection: sqlite3.Connection, business_id: int, *, account_id: int | None = None,
    start: str | None = None, end: str | None = None,
) -> list[dict[str, Any]]:
    """Every credit (money in) with how it arrived and how it is currently accounted for."""
    clauses = ["t.business_id = ?", "t.signed_amount > 0"]
    params: list[Any] = [business_id]
    if account_id:
        clauses.append("t.account_id = ?"); params.append(account_id)
    if start:
        clauses.append("t.transaction_date >= ?"); params.append(start)
    if end:
        clauses.append("t.transaction_date <= ?"); params.append(end)
    rows = [dict(row) for row in connection.execute(
        f"""SELECT t.id, t.transaction_date, a.name AS account, t.description, t.signed_amount,
                   t.treatment, t.status, t.counterparty, t.notes, c.name AS category,
                   (SELECT COUNT(*) FROM check_register r WHERE r.transaction_id = t.id) AS linked_checks
            FROM transactions t JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE {' AND '.join(clauses)} ORDER BY t.transaction_date DESC, t.id DESC""", params)]
    for row in rows:
        row["kind"] = deposit_kind(row["description"])
    return rows


def suggest_transfer_counterpart(
    connection: sqlite3.Connection, business_id: int, transaction_id: int,
) -> dict[str, Any] | None:
    """Guess the other side of an internal transfer from records already in the books.

    First looks for the opposite leg (same amount, opposite sign, another account of this
    business, within a week). Then falls back to how similar past transfers on this account
    were recorded. Returns related_account_id, related_account_name, counterparty and reason.
    """
    txn = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND business_id = ?", (transaction_id, business_id)).fetchone()
    if txn is None:
        return None
    leg = connection.execute(
        """SELECT t.id, t.transaction_date, t.account_id, a.name AS account_name
           FROM transactions t JOIN accounts a ON a.id = t.account_id
           WHERE t.business_id = ? AND t.account_id <> ? AND ABS(t.signed_amount + ?) < 0.005
             AND ABS(julianday(t.transaction_date) - julianday(?)) <= 7
           ORDER BY (t.treatment = 'Transfer') DESC, (t.status = 'needs_review') DESC,
                    ABS(julianday(t.transaction_date) - julianday(?)), t.id LIMIT 1""",
        (business_id, txn["account_id"], txn["signed_amount"], txn["transaction_date"],
         txn["transaction_date"])).fetchone()
    if leg:
        return {"related_account_id": int(leg["account_id"]), "related_account_name": leg["account_name"],
                "counterparty": leg["account_name"], "transaction_id": int(leg["id"]),
                "reason": f"Matching {abs(float(txn['signed_amount'])):,.2f} on {leg['transaction_date']} in {leg['account_name']}"}
    pattern = suggested_vendor_pattern(txn["description"])
    if len(pattern) >= 6:
        rows = connection.execute(
            """SELECT t.related_account_id, a.name AS account_name, t.counterparty, COUNT(*) AS n
               FROM transactions t LEFT JOIN accounts a ON a.id = t.related_account_id
               WHERE t.business_id = ? AND t.account_id = ? AND t.id <> ? AND t.treatment = 'Transfer'
                 AND (t.related_account_id IS NOT NULL OR TRIM(COALESCE(t.counterparty, '')) <> '')
                 AND t.normalized_description LIKE ?
               GROUP BY t.related_account_id, t.counterparty ORDER BY n DESC LIMIT 1""",
            (business_id, txn["account_id"], transaction_id, f"%{pattern}%")).fetchall()
        if rows:
            row = rows[0]
            return {"related_account_id": row["related_account_id"], "related_account_name": row["account_name"],
                    "counterparty": row["counterparty"] or row["account_name"] or "",
                    "reason": f"Recorded this way on {row['n']} earlier similar transfer(s)"}
    return None


def suggest_deposit_check_details(
    connection: sqlite3.Connection, business_id: int, transaction_id: int,
) -> dict[str, Any]:
    """Pre-fill for the deposited-check form: check number, who it came from, memo, category, treatment.

    An opposite entry in another account (an internal transfer) wins, and brings the check number
    of the check written on that account. Otherwise the most recent earlier deposit with the same
    bank description is used.
    """
    txn = connection.execute(
        "SELECT description, normalized_description FROM transactions WHERE id = ? AND business_id = ?",
        (transaction_id, business_id)).fetchone()
    if txn is None:
        return {}
    guess = suggest_transfer_counterpart(connection, business_id, transaction_id)
    if guess and guess.get("transaction_id"):
        linked = connection.execute(
            """SELECT r.check_number, r.payee, r.memo FROM check_register r
               WHERE r.transaction_id = ? AND r.check_type = 'payment' ORDER BY r.id LIMIT 1""",
            (guess["transaction_id"],)).fetchone()
        return {
            "check_number": linked["check_number"] if linked else "",
            "payer": guess["related_account_name"],
            "memo": (linked["memo"] if linked else "") or "Internal transfer",
            "category": "Internal transfer", "treatment": "Transfer",
            "reason": guess["reason"] + (f" (check #{linked['check_number']})" if linked else ""),
        }
    previous = connection.execute(
        """SELECT r.payee, r.memo, r.treatment, c.name AS category
           FROM check_register r JOIN transactions t ON t.id = r.transaction_id
           LEFT JOIN categories c ON c.id = r.category_id
           WHERE r.business_id = ? AND r.check_type = 'deposit' AND t.id <> ?
             AND t.normalized_description = ? AND TRIM(COALESCE(r.payee, '')) <> ''
           ORDER BY r.cleared_date DESC, r.id DESC LIMIT 1""",
        (business_id, transaction_id, txn["normalized_description"])).fetchone()
    if previous:
        return {"check_number": "", "payer": previous["payee"], "memo": previous["memo"] or "",
                "category": previous["category"], "treatment": previous["treatment"],
                "reason": "Same as an earlier deposit with this description"}
    return {}


def last_deposit_details(
    connection: sqlite3.Connection, business_id: int, *, treatment: str,
    category: str | None = None, exclude_transaction_id: int | None = None,
) -> dict[str, Any] | None:
    """Details of the most recent earlier deposit recorded with this treatment (and category).

    Looks at deposited checks first, then at bank transactions, so a Transfer or Internal transfer
    selection can offer who it came from and the memo used last time.
    """
    clauses = ["r.business_id = ?", "r.check_type = 'deposit'", "r.treatment = ?"]
    params: list[Any] = [business_id, treatment]
    if category:
        clauses.append("c.name = ?"); params.append(category)
    if exclude_transaction_id:
        clauses.append("COALESCE(r.transaction_id, 0) <> ?"); params.append(exclude_transaction_id)
    row = connection.execute(
        f"""SELECT r.check_number, r.payee, r.memo, r.cleared_date, r.amount, c.name AS category
            FROM check_register r LEFT JOIN categories c ON c.id = r.category_id
            WHERE {' AND '.join(clauses)} AND TRIM(COALESCE(r.payee, '')) <> ''
            ORDER BY r.cleared_date DESC, r.id DESC LIMIT 1""", params).fetchone()
    if row:
        return {"payer": row["payee"], "memo": row["memo"] or "", "check_number": "",
                "reason": f"last {treatment.lower()} deposit: {row['cleared_date']}, ${float(row['amount']):,.2f}"}
    clauses = ["t.business_id = ?", "t.signed_amount > 0", "t.treatment = ?", "t.status = 'confirmed'",
               "TRIM(COALESCE(t.counterparty, '')) <> ''"]
    params = [business_id, treatment]
    if category:
        clauses.append("c.name = ?"); params.append(category)
    if exclude_transaction_id:
        clauses.append("t.id <> ?"); params.append(exclude_transaction_id)
    row = connection.execute(
        f"""SELECT t.counterparty, t.notes, t.transaction_date, t.signed_amount
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE {' AND '.join(clauses)} ORDER BY t.transaction_date DESC, t.id DESC LIMIT 1""", params).fetchone()
    if row:
        return {"payer": row["counterparty"], "memo": row["notes"] or "", "check_number": "",
                "reason": f"last {treatment.lower()} transaction: {row['transaction_date']}, ${float(row['signed_amount']):,.2f}"}
    return None


DEPOSIT_TREATMENTS = (
    "Revenue", "Loan draw", "Transfer", "Owner contribution", "Receivable repayment",
    "Revenue refund", "Expense refund", "Excluded",
)


def classify_deposits(
    connection: sqlite3.Connection, *, business_id: int, transaction_ids: list[int],
    treatment: str, counterparty: str = "", category_id: int | None = None,
    related_account_id: int | None = None, notes: str | None = None,
    fill_transfer_from_records: bool = False,
) -> int:
    """Account for several deposits at once. Only credits of this business are touched."""
    if treatment not in DEPOSIT_TREATMENTS:
        raise ValueError(f"{treatment} is not a valid treatment for a deposit.")
    done = 0
    for transaction_id in transaction_ids:
        row = connection.execute(
            "SELECT id FROM transactions WHERE id = ? AND business_id = ? AND signed_amount > 0",
            (int(transaction_id), business_id)).fetchone()
        if not row:
            continue
        related = related_account_id
        party = counterparty
        if treatment == "Transfer" and fill_transfer_from_records and (related is None or not party.strip()):
            guess = suggest_transfer_counterpart(connection, business_id, int(transaction_id))
            if guess:
                related = related if related is not None else guess["related_account_id"]
                party = party if party.strip() else (guess["counterparty"] or "")
        update_transaction_classification(
            connection, int(transaction_id), category_id=category_id, treatment=treatment,
            related_account_id=related, notes=notes or None)
        if party.strip():
            set_transaction_counterparty(
                connection, business_id=business_id, transaction_id=int(transaction_id),
                counterparty=party)
        done += 1
    return done


def list_unreconciled_deposits(
    connection: sqlite3.Connection, business_id: int, account_id: int,
    start: str | None = None, end: str | None = None, checks_only: bool = True,
) -> list[dict[str, Any]]:
    """Credits on an account that have no check-register entry yet."""
    clauses = ["t.business_id = ?", "t.account_id = ?", "t.signed_amount > 0",
               "NOT EXISTS (SELECT 1 FROM check_register r WHERE r.transaction_id = t.id)"]
    params: list[Any] = [business_id, account_id]
    if start:
        clauses.append("t.transaction_date >= ?"); params.append(start)
    if end:
        clauses.append("t.transaction_date <= ?"); params.append(end)
    rows = [dict(row) for row in connection.execute(
        f"""SELECT t.id, t.transaction_date, t.description, t.signed_amount, t.treatment, t.status
            FROM transactions t WHERE {' AND '.join(clauses)}
            ORDER BY t.transaction_date, t.id""", params)]
    if checks_only:
        rows = [row for row in rows if looks_like_check_deposit(row["description"])]
    return rows


def confirm_deposit_checks(
    connection: sqlite3.Connection,
    *,
    business_id: int,
    account_id: int,
    transaction_id: int,
    bank_name: str,
    account_last4: str,
    deposited_checks: list[dict[str, Any]],
    category_id: int | None,
    treatment: str,
) -> list[int]:
    """Record the checks that made up one bank deposit and tie them to that transaction.

    Each item needs ``amount`` and may carry ``check_number``, ``payer``, ``memo``, ``written_date``
    and ``image_file``. The amounts must add up to the deposit exactly.
    """
    transaction = connection.execute(
        "SELECT transaction_date, signed_amount FROM transactions WHERE id=? AND business_id=? AND account_id=?",
        (transaction_id, business_id, account_id),
    ).fetchone()
    if transaction is None:
        raise ValueError("That deposit does not belong to this business and account.")
    deposit = round(float(transaction["signed_amount"]), 2)
    if deposit <= 0:
        raise ValueError("A deposit must be a credit (positive amount).")
    if not deposited_checks:
        raise ValueError("Add at least one deposited check.")
    total = round(sum(float(item["amount"]) for item in deposited_checks), 2)
    if abs(total - deposit) >= 0.005:
        raise ValueError(f"The checks add up to ${total:,.2f} but the deposit is ${deposit:,.2f}.")
    if any(float(item["amount"]) <= 0 for item in deposited_checks):
        raise ValueError("Every check amount must be greater than zero.")
    cleared = transaction["transaction_date"]
    month_end = (datetime.strptime(cleared, "%Y-%m-%d").replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    ids = []
    for position, item in enumerate(deposited_checks, start=1):
        number = str(item.get("check_number") or "").strip() or f"DEP-{transaction_id}-{position}"
        ids.append(confirm_check(
            connection, business_id=business_id, account_id=account_id, transaction_id=transaction_id,
            bank_name=bank_name, account_last4=account_last4, statement_date=month_end.date().isoformat(),
            check_number=number, amount=float(item["amount"]), written_date=item.get("written_date"),
            cleared_date=cleared, payee=str(item.get("payer") or ""), memo=str(item.get("memo") or ""),
            category_id=category_id, treatment=treatment,
            source_file_name=str(item.get("image_file") or ""), check_type="deposit"))
    ensure_deposit_log_entries(connection, business_id)
    return ids
