from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from books import db, importers, statements


class BooksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        db.init_db(self.path)
        with db.connect(self.path) as connection:
            self.business = db.get_or_create_business(connection, "Test Business")
            self.account = db.get_or_create_account(connection, self.business, "Checking", "checking")
            self.category = db.get_or_create_category(connection, self.business, "Hosting", "Expense")

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_and_rule_learning(self):
        with db.connect(self.path) as connection:
            first, duplicate, _ = db.insert_transaction(connection, business_id=self.business,
                account_id=self.account, transaction_date="2026-01-01", posting_date=None,
                description="DIGITALOCEAN.COM 123", source_amount=-10, signed_amount=-10)
            self.assertFalse(duplicate)
            db.classify_transaction(connection, first, category_id=self.category, treatment="Expense",
                                    pattern="DIGITALOCEAN.COM")
            _, duplicate, automatic = db.insert_transaction(connection, business_id=self.business,
                account_id=self.account, transaction_date="2026-02-01", posting_date=None,
                description="DIGITALOCEAN.COM 456", source_amount=-12, signed_amount=-12)
            self.assertFalse(duplicate)
            self.assertTrue(automatic)
            _, duplicate, _ = db.insert_transaction(connection, business_id=self.business,
                account_id=self.account, transaction_date="2026-02-01", posting_date=None,
                description="DIGITALOCEAN.COM 456", source_amount=-12, signed_amount=-12)
            self.assertTrue(duplicate)

    def test_import_and_undo(self):
        text = "Date,Description,Amount\n11/01/2026,Client payment,100.00\n11/02/2026,Fee,-5.00\n"
        rows = importers.preview_csv(text, "checking")
        with db.connect(self.path) as connection:
            result = importers.commit_rows(connection, business_id=self.business, account_id=self.account,
                                            account_type="checking", rows=rows, source_name="paste.csv")
            self.assertEqual(result["imported"], 2)
            self.assertEqual(db.undo_import_batch(connection, result["batch_id"]), 2)

    def test_line_of_credit_balance(self):
        with db.connect(self.path) as connection:
            loc = db.get_or_create_account(connection, self.business, "LOC", "line_of_credit")
            db.add_loan_event(connection, business_id=self.business, loc_account_id=loc,
                              event_date="2026-01-01", event_type="draw", amount=5000)
            db.add_loan_event(connection, business_id=self.business, loc_account_id=loc,
                              event_date="2026-02-01", event_type="principal_payment", amount=1200)
            self.assertEqual(db.loc_balance(connection, loc), 3800)

    def test_direct_transaction_category_update(self):
        with db.connect(self.path) as connection:
            transaction_id, _, _ = db.insert_transaction(connection, business_id=self.business,
                account_id=self.account, transaction_date="2026-03-01", posting_date=None,
                description="Editable row", source_amount=-25, signed_amount=-25)
            db.update_transaction_classification(connection, transaction_id,
                                                 category_id=self.category, treatment="Expense")
            updated = db.get_transaction(connection, transaction_id)
            self.assertEqual(updated["category_id"], self.category)
            self.assertEqual(updated["treatment"], "Expense")
            self.assertEqual(updated["status"], "confirmed")

    def test_vendor_mapping_classifies_waiting_and_future_rows(self):
        with db.connect(self.path) as connection:
            waiting_id, _, _ = db.insert_transaction(connection, business_id=self.business,
                account_id=self.account, transaction_date="2026-04-01", posting_date=None,
                description="MULTIVISIONOPERA DES:ROVAR INFO", source_amount=500, signed_amount=500)
            _, applied = db.upsert_vendor(connection, business_id=self.business,
                name="Multivision Opera", match_pattern="MULTIVISIONOPERA",
                category_id=self.category, treatment="Revenue", apply_existing=True)
            self.assertEqual(applied, 1)
            self.assertEqual(db.get_transaction(connection, waiting_id)["treatment"], "Revenue")
            _, _, automatic = db.insert_transaction(connection, business_id=self.business,
                account_id=self.account, transaction_date="2026-05-01", posting_date=None,
                description="MULTIVISIONOPERA DES:NEW PAYMENT", source_amount=700, signed_amount=700)
            self.assertTrue(automatic)
            self.assertEqual(len(db.list_vendors(connection, self.business)), 1)

    def test_vendor_pattern_suggestion(self):
        self.assertEqual(
            db.suggested_vendor_pattern("MULTIVISIONOPERA DES:ROVAR INFO ID:123"),
            "MULTIVISIONOPERA",
        )

    def test_check_filename_suggestion_and_register(self):
        checks = [
            {"check_number": "144", "amount": 5000.0},
            {"check_number": "145", "amount": 5833.0},
        ]
        self.assertEqual(statements.suggest_check_index(checks, "5833.pdf"), 1)
        self.assertEqual(statements.match_check_index(checks, "5833.pdf"), 1)
        self.assertIsNone(statements.match_check_index(checks, "unrelated.pdf"))
        with db.connect(self.path) as connection:
            transaction_id, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-09-14", posting_date=None,
                description="CHECK 145", source_amount=-5833, signed_amount=-5833)
            candidates = db.find_check_transaction_candidates(
                connection, business_id=self.business, account_id=self.account,
                amount=5833, cleared_date="2026-09-14")
            self.assertEqual(candidates[0]["id"], transaction_id)
            db.confirm_check(
                connection, business_id=self.business, account_id=self.account,
                transaction_id=transaction_id, bank_name="Truist", account_last4="1049",
                statement_date="2026-09-30", check_number="145", amount=5833,
                written_date="2026-08-28", cleared_date="2026-09-14",
                payee="Colina Tech Solutions LLC", memo="Project payment",
                category_id=self.category, treatment="Expense", source_file_name="5833.pdf")
            register = db.list_check_register(connection, self.business)
            self.assertEqual(len(register), 1)
            self.assertEqual(register[0]["payee"], "Colina Tech Solutions LLC")
            self.assertEqual(register[0]["check_type"], "payment")
            self.assertEqual(db.get_transaction(connection, transaction_id)["status"], "confirmed")
            db.confirm_check(
                connection, business_id=self.business, account_id=self.account,
                transaction_id=transaction_id, bank_name="Truist", account_last4="1049",
                statement_date="2026-09-30", check_number="145", amount=5833,
                written_date="2026-08-28", cleared_date="2026-09-14",
                payee="Updated payee", memo="Updated memo",
                category_id=self.category, treatment="Expense", source_file_name="5833.pdf")
            updated_register = db.list_check_register(connection, self.business)
            self.assertEqual(len(updated_register), 1)
            self.assertEqual(updated_register[0]["payee"], "Updated payee")

    def test_check_direction_matching_and_delete(self):
        with db.connect(self.path) as connection:
            deposit_id, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-10-01", posting_date=None,
                description="DEPOSITED CHECK", source_amount=2500, signed_amount=2500)
            payment_id, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-10-01", posting_date=None,
                description="CHECK PAYMENT", source_amount=-2500, signed_amount=-2500)
            deposits = db.find_check_transaction_candidates(
                connection, business_id=self.business, account_id=self.account,
                amount=2500, cleared_date="2026-10-01", check_type="deposit")
            payments = db.find_check_transaction_candidates(
                connection, business_id=self.business, account_id=self.account,
                amount=2500, cleared_date="2026-10-01", check_type="payment")
            self.assertEqual([item["id"] for item in deposits], [deposit_id])
            self.assertEqual([item["id"] for item in payments], [payment_id])
            check_id = db.confirm_check(
                connection, business_id=self.business, account_id=self.account,
                transaction_id=deposit_id, bank_name="Bank of America", account_last4="1234",
                statement_date="2026-10-31", check_number="DEP-101", amount=2500,
                written_date="2026-10-01", cleared_date="2026-10-01",
                payee="Customer deposit", memo="Invoice payment",
                category_id=self.category, treatment="Revenue", source_file_name="deposit.pdf",
                check_type="deposit")
            register = db.list_check_register(connection, self.business)
            self.assertEqual(register[0]["check_type"], "deposit")
            with self.assertRaises(ValueError):
                db.confirm_check(
                    connection, business_id=self.business, account_id=self.account,
                    transaction_id=payment_id, bank_name="Bank of America", account_last4="1234",
                    statement_date="2026-10-31", check_number="DEP-102", amount=2500,
                    written_date="2026-10-01", cleared_date="2026-10-01",
                    payee="Wrong direction", memo="", category_id=self.category,
                    treatment="Revenue", source_file_name="deposit-2.pdf", check_type="deposit")
            self.assertTrue(db.delete_check_register_entry(
                connection, business_id=self.business, check_id=check_id))
            self.assertEqual(db.list_check_register(connection, self.business), [])

    def test_check_number_match_ranks_first_and_sync(self):
        with db.connect(self.path) as connection:
            other, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-09-15", posting_date=None,
                description="WIRE OUT", source_amount=-5000, signed_amount=-5000)
            named, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-09-20", posting_date=None,
                description="Check #99", source_amount=-5000, signed_amount=-5000)
            found = db.find_check_transaction_candidates(
                connection, business_id=self.business, account_id=self.account, amount=5000,
                cleared_date="2026-09-15", check_type="payment", check_number="99")
            self.assertEqual([item["id"] for item in found], [named, other])
            self.assertTrue(found[0]["number_match"])
            self.assertFalse(found[1]["number_match"])
            kwargs = dict(
                business_id=self.business, account_id=self.account, bank_name="Truist",
                account_last4="1049", statement_date="2026-09-30", check_number="99",
                amount=5000, written_date="2026-09-10", cleared_date="2026-09-15",
                payee="Acme LLC", memo="", category_id=self.category, treatment="Expense",
                source_file_name="x.pdf")
            check_id = db.confirm_check(connection, transaction_id=named, **kwargs)
            self.assertEqual(db.get_transaction(connection, named)["status"], "confirmed")
            # relinking to another transaction sends the old one back to review
            db.confirm_check(connection, transaction_id=other, **kwargs)
            self.assertEqual(db.get_transaction(connection, named)["status"], "needs_review")
            self.assertEqual(db.get_transaction(connection, named)["treatment"], "Needs review")
            # deleting can send the linked transaction back to review as well
            self.assertTrue(db.delete_check_register_entry(
                connection, business_id=self.business, check_id=check_id, reset_transaction=True))
            self.assertEqual(db.get_transaction(connection, other)["status"], "needs_review")

    def test_payee_history_and_canonical_spelling(self):
        with db.connect(self.path) as connection:
            db.confirm_check(
                connection, business_id=self.business, account_id=self.account,
                transaction_id=None, bank_name="Truist", account_last4="1049",
                statement_date="2026-09-30", check_number="147", amount=11000,
                written_date="2026-09-15", cleared_date="2026-09-15",
                payee="Colina Tech Solutions LLC", memo="Loan", category_id=None,
                treatment="Loan receivable", source_file_name="x.pdf")
            history = db.payee_history(connection, self.business)
            self.assertEqual(history[0]["payee"], "Colina Tech Solutions LLC")
            self.assertEqual(history[0]["treatment"], "Loan receivable")
            self.assertEqual(db.canonical_payee(connection, self.business, "colina tech solutions"),
                             "Colina Tech Solutions LLC")
            self.assertEqual(db.canonical_payee(connection, self.business, "Someone Else"), "Someone Else")

    def test_truist_text_parser(self):
        from books import statements
        text = ("TRUIST BANK\nFor 09/30/2026\nBUSINESS CHECKING 1000091049\n"
                "previous balance as of 08/31/2026 $10,000.00\nnew balance as of 09/30/2026 = $5,000.00\n"
                "Checks\nDATE CHECK # AMOUNT\n09/15 147 11,000.00\n09/16 *148 250.00\n"
                "Other withdrawals, debits and service charges\nTotal checks = $11,250.00\n")
        parsed = statements.parse_truist_text(text, 2)
        self.assertEqual(parsed["statement_date"], "2026-09-30")
        self.assertEqual(parsed["account_last4"], "1049")
        self.assertEqual([(c["check_number"], c["cleared_date"], c["amount"]) for c in parsed["checks"]],
                         [("147", "2026-09-15", 11000.0), ("148", "2026-09-16", 250.0)])
        self.assertEqual(parsed["check_total"], 11250.0)
        with self.assertRaises(ValueError):
            statements.parse_truist_text("Some other bank", 1)

    def test_boa_text_parser(self):
        from books import statements
        text = ("Bank of America\nYour checking account for September 1, 2026 to September 30, 2026\n"
                "Account number: 1234 5678 9012\nBeginning balance on September 1, 2026 $1,000.00\n"
                "Ending balance on September 30, 2026 $500.00\nChecks\nDate Check # Amount\n"
                "09/15/26 147 -11,000.00\n09/16/26 149* -250.00\nTotal checks -$11,250.00\n")
        parsed = statements.parse_boa_text(text, 3)
        self.assertEqual(parsed["statement_date"], "2026-09-30")
        self.assertEqual(parsed["account_last4"], "9012")
        self.assertEqual([c["check_number"] for c in parsed["checks"]], ["147", "149"])
        self.assertEqual(parsed["check_total"], 11250.0)
        self.assertEqual(parsed["closing_balance"], 500.0)

    def test_check_file_matching_and_account_last4(self):
        from books import statements
        checks = [{"check_number": "147", "amount": 11000.0}, {"check_number": "148", "amount": 250.0},
                  {"check_number": "149", "amount": 250.0}]
        self.assertEqual(statements.match_check_index(checks, "11000.pdf"), 0)
        self.assertEqual(statements.match_check_index(checks, "250-149.pdf"), 2)
        self.assertIsNone(statements.match_check_index(checks, "250.pdf"))
        self.assertIsNone(statements.match_check_index(checks, "scan.pdf"))
        with db.connect(self.path) as connection:
            db.set_account_last4(connection, self.account, "xx1049")
            self.assertEqual(
                next(a for a in db.list_accounts(connection, self.business) if a["id"] == self.account)["last4"],
                "1049")

    def test_statement_log_snapshot_and_archive_rows(self):
        from books import backup
        statement_checks = [
            {"check_number": "147", "cleared_date": "2026-09-15", "amount": 11000.0},
            {"check_number": "148", "cleared_date": "2026-09-16", "amount": 250.0},
        ]
        log_args = dict(business_id=self.business, account_id=self.account, bank_name="Truist",
                        account_last4="1049", statement_date="2026-09-30",
                        statement_file_name="truist-sep-2026.pdf", statement_check_total=11250.0,
                        statement_checks=statement_checks)
        with db.connect(self.path) as connection:
            db.log_statement_reconciliation(connection, **log_args)
            self.assertEqual(db.list_statement_log(connection, self.business)[0]["status"], "Not started")
            db.confirm_check(
                connection, business_id=self.business, account_id=self.account, transaction_id=None,
                bank_name="Truist", account_last4="1049", statement_date="2026-09-30", check_number="147",
                amount=11000, written_date="2026-09-15", cleared_date="2026-09-15", payee="Colina",
                memo="", category_id=None, treatment="Loan receivable", source_file_name="11000.pdf")
            db.log_statement_reconciliation(connection, **log_args)
            header = db.list_statement_log(connection, self.business)
            self.assertEqual(len(header), 1)
            self.assertEqual((header[0]["status"], header[0]["checks_mapped"], header[0]["checks_listed"]),
                             ("In progress", 1, 2))
            self.assertEqual(header[0]["statement_file_name"], "truist-sep-2026.pdf")
            db.confirm_check(
                connection, business_id=self.business, account_id=self.account, transaction_id=None,
                bank_name="Truist", account_last4="1049", statement_date="2026-09-30", check_number="148",
                amount=250, written_date="2026-09-16", cleared_date="2026-09-16", payee="Acme",
                memo="", category_id=None, treatment="Expense", source_file_name="250.pdf")
            db.log_statement_reconciliation(connection, **{**log_args, "statement_file_name": None})
            header = db.list_statement_log(connection, self.business)[0]
            self.assertEqual(header["status"], "Reconciled")
            self.assertEqual(header["statement_file_name"], "truist-sep-2026.pdf")  # name is kept
            rows = db.statement_log_rows(connection, self.business)
            self.assertEqual([(r["check_number"], r["reconciled"], r["counterparty"]) for r in rows],
                             [("147", "Yes", "Colina"), ("148", "Yes", "Acme")])
            self.assertEqual(rows[0]["statement_file"], "truist-sep-2026.pdf")

    def test_backup_restore_roundtrip(self):
        from books import backup
        with db.connect(self.path) as connection:
            before = connection.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        made = backup.create_backup(self.path, "manual")
        self.assertTrue(made.exists())
        self.assertEqual(backup.validate_backup(made)["businesses"], before)
        with db.connect(self.path) as connection:
            db.get_or_create_business(connection, "Another Co")
        safety = backup.restore_backup(self.path, made)
        with db.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM businesses").fetchone()[0], before)
        self.assertEqual(backup.validate_backup(safety)["businesses"], before + 1)
        names = [row["name"] for row in backup.list_backups(self.path)]
        self.assertIn(made.name, names)
        backup.delete_backup(self.path, made.name)
        self.assertNotIn(made.name, [row["name"] for row in backup.list_backups(self.path)])
        with self.assertRaises(ValueError):
            backup.backup_path(self.path, "../../etc/passwd")
        bogus = Path(self.path).parent / "bogus.db"
        bogus.write_text("not a database")
        with self.assertRaises(ValueError):
            backup.validate_backup(bogus)
        first = backup.maybe_daily_backup(self.path)
        self.assertIsNotNone(first)
        self.assertIsNone(backup.maybe_daily_backup(self.path))  # already backed up today

    def test_deposited_checks_reconciliation(self):
        with db.connect(self.path) as connection:
            deposit, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-04-08", posting_date=None,
                description="Counter Credit", source_amount=8000, signed_amount=8000)
            ach, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-04-09", posting_date=None,
                description="Bill.com ACH CREDIT", source_amount=900, signed_amount=900)
            pending = db.list_unreconciled_deposits(connection, self.business, self.account)
            self.assertEqual([row["id"] for row in pending], [deposit])  # ACH is not a check deposit
            self.assertEqual(len(db.list_unreconciled_deposits(
                connection, self.business, self.account, checks_only=False)), 2)
            with self.assertRaises(ValueError):  # must add up to the deposit
                db.confirm_deposit_checks(
                    connection, business_id=self.business, account_id=self.account, transaction_id=deposit,
                    bank_name="BOA", account_last4="", category_id=None, treatment="Revenue",
                    deposited_checks=[{"amount": 5000, "payer": "A"}])
            ids = db.confirm_deposit_checks(
                connection, business_id=self.business, account_id=self.account, transaction_id=deposit,
                bank_name="BOA", account_last4="", category_id=None, treatment="Revenue",
                deposited_checks=[{"amount": 5000, "payer": "Customer A", "check_number": "1201"},
                                  {"amount": 3000, "payer": "Customer B"}])
            self.assertEqual(len(ids), 2)
            register = db.list_check_register(connection, self.business)
            self.assertEqual({r["check_type"] for r in register}, {"deposit"})
            self.assertEqual(sorted(r["amount"] for r in register), [3000.0, 5000.0])
            self.assertEqual(db.get_transaction(connection, deposit)["treatment"], "Revenue")
            self.assertEqual(db.list_unreconciled_deposits(connection, self.business, self.account), [])
            # deleting one check keeps the deposit reconciled; deleting the last sends it back to review
            self.assertTrue(db.delete_check_register_entry(
                connection, business_id=self.business, check_id=ids[0], reset_transaction=True))
            self.assertEqual(db.get_transaction(connection, deposit)["status"], "confirmed")
            self.assertTrue(db.delete_check_register_entry(
                connection, business_id=self.business, check_id=ids[1], reset_transaction=True))
            self.assertEqual(db.get_transaction(connection, deposit)["status"], "needs_review")

    def test_multi_check_pdf_grouping_and_text_match(self):
        from books import statements
        checks = [{"check_number": "147", "amount": 11000.0}, {"check_number": "148", "amount": 250.0},
                  {"check_number": "149", "amount": 975.5}]
        images = [(b"a", "p1"), (b"b", "p1"), (b"c", "p2"), (b"d", "p2"), (b"e", "p3")]
        groups = statements.group_check_images(images, 2)
        self.assertEqual([[i[0] for i in g] for g in groups], [[b"a", b"b"], [b"c", b"d"], [b"e"]])
        self.assertEqual(statements.group_check_images(images, 1)[4][0][0], b"e")
        self.assertEqual(statements.match_text_to_check(checks, "Pay to Acme $975.50 Dollars"), 2)
        self.assertEqual(statements.match_text_to_check(checks, "Check number: 148"), 1)
        self.assertIsNone(statements.match_text_to_check(checks, "nothing useful 12.34"))
        explicit = {"name": "scan.pdf · check 2", "check_index": 1}
        self.assertEqual(statements.resolve_check_index(checks, explicit), 1)
        self.assertIsNone(statements.resolve_check_index(checks, {"name": "x.pdf", "check_index": None}))
        self.assertEqual(statements.resolve_check_index(checks, {"name": "11000.pdf"}), 0)

    def test_transaction_counterparty_for_loans(self):
        with db.connect(self.path) as connection:
            wire, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-10-02", posting_date=None,
                description="WIRE OUT", source_amount=-4000, signed_amount=-4000)
            db.update_transaction_classification(connection, wire, category_id=None, treatment="Loan receivable")
            self.assertEqual(db.list_loan_receivables(connection, self.business)[0]["counterparty"],
                             "(Bank transactions without a counterparty)")
            stored = db.set_transaction_counterparty(
                connection, business_id=self.business, transaction_id=wire, counterparty="Colina Tech Solutions LLC")
            self.assertEqual(stored, "Colina Tech Solutions LLC")
            row = next(r for r in db.list_transactions(connection, self.business) if r["id"] == wire)
            self.assertEqual(row["counterparty"], "Colina Tech Solutions LLC")
            self.assertEqual(db.list_loan_receivables(connection, self.business),
                             [{"counterparty": "Colina Tech Solutions LLC", "lent": 4000.0,
                               "repaid": 0.0, "balance_owed": 4000.0}])
            # case/punctuation differences reuse the existing spelling; a different suffix is respected
            other, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-10-05", posting_date=None,
                description="WIRE IN", source_amount=1000, signed_amount=1000)
            db.update_transaction_classification(connection, other, category_id=None, treatment="Receivable repayment")
            self.assertEqual(db.set_transaction_counterparty(
                connection, business_id=self.business, transaction_id=other, counterparty="colina tech solutions, llc"),
                "Colina Tech Solutions LLC")
            self.assertEqual(db.list_loan_receivables(connection, self.business)[0]["balance_owed"], 3000.0)
            self.assertEqual(db.LOAN_ROLES["Loan draw"], "Borrowed from")
            # confirming a check copies the payee onto the linked transaction, and edits flow back
            check_txn, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-10-06", posting_date=None,
                description="Check #50", source_amount=-700, signed_amount=-700)
            db.confirm_check(
                connection, business_id=self.business, account_id=self.account, transaction_id=check_txn,
                bank_name="Truist", account_last4="", statement_date="2026-10-31", check_number="50",
                amount=700, written_date=None, cleared_date="2026-10-06", payee="Acme Corp", memo="",
                category_id=None, treatment="Expense", source_file_name="x.pdf")
            self.assertEqual(next(r for r in db.list_transactions(connection, self.business)
                                  if r["id"] == check_txn)["counterparty"], "Acme Corp")
            db.set_transaction_counterparty(
                connection, business_id=self.business, transaction_id=check_txn, counterparty="Acme Inc")
            self.assertEqual(db.list_check_register(connection, self.business)[0]["payee"], "Acme Inc")
            # balances merge spellings that differ only by suffix
            merged, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-10-07", posting_date=None,
                description="WIRE OUT 2", source_amount=-500, signed_amount=-500)
            db.update_transaction_classification(connection, merged, category_id=None, treatment="Loan receivable")
            db.set_transaction_counterparty(
                connection, business_id=self.business, transaction_id=merged, counterparty="Colina Tech Solutions")
            rows = db.list_loan_receivables(connection, self.business)
            self.assertEqual([(r["counterparty"], r["balance_owed"]) for r in rows],
                             [("Colina Tech Solutions LLC", 3500.0)])

    def test_loan_receivable_balance(self):
        self.assertIn("Loan receivable", db.TREATMENTS)
        with db.connect(self.path) as connection:
            for number, amount, treatment, check_type in (
                ("147", 11000, "Loan receivable", "payment"),
                ("DEP-1", 3000, "Receivable repayment", "deposit"),
            ):
                db.confirm_check(
                    connection, business_id=self.business, account_id=self.account,
                    transaction_id=None, bank_name="Truist", account_last4="1049",
                    statement_date="2026-09-30", check_number=number, amount=amount,
                    written_date="2026-09-15", cleared_date="2026-09-15",
                    payee="Colina Tech Solutions LLC", memo="Loan", category_id=None,
                    treatment=treatment, source_file_name="x.pdf", check_type=check_type)
            rows = db.list_loan_receivables(connection, self.business)
            self.assertEqual(rows, [{"counterparty": "Colina Tech Solutions LLC",
                                     "lent": 11000.0, "repaid": 3000.0, "balance_owed": 8000.0}])

    def test_bank_detection_rejects_non_statement(self):
        from pypdf import PdfWriter
        from io import BytesIO

        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(output)
        self.assertEqual(statements.detect_bank(output.getvalue()), "Other / unknown")
        with self.assertRaises(ValueError):
            statements.parse_statement(output.getvalue())

    def test_boa_check_rows_with_sequence_gap_marker(self):
        rows = statements.parse_boa_check_rows(
            "01/14/26252 -7,065.2801/14/26255* -4,000.0001/14/26253 -3,600.00"
        )
        self.assertEqual(rows, [
            ("01/14/26", "252", 7065.28),
            ("01/14/26", "255", 4000.0),
            ("01/14/26", "253", 3600.0),
        ])
        spaced_rows = statements.parse_boa_check_rows(
            "10/08/26 263 -3,520.00\n01/14/26 255* -4,000.00"
        )
        self.assertEqual(spaced_rows, [
            ("10/08/26", "263", 3520.0),
            ("01/14/26", "255", 4000.0),
        ])

    def test_bulk_deposit_classification(self):
        with db.connect(self.path) as connection:
            ids = []
            for day, desc, amount in [("2026-04-21", "BKOFAMERICA ATM 04/21 DEPOSIT NORMANDY", 9576),
                                      ("2026-05-06", "BKOFAMERICA MOBILE 05/06 DEPOSIT *MOBILE MD", 10218),
                                      ("2026-06-01", "WIRE FROM ACME", 500)]:
                new, _, _ = db.insert_transaction(
                    connection, business_id=self.business, account_id=self.account,
                    transaction_date=day, posting_date=None, description=desc,
                    source_amount=amount, signed_amount=amount)
                ids.append(new)
            outgoing, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-06-02", posting_date=None, description="PAYMENT",
                source_amount=-50, signed_amount=-50)
            kinds = {d["id"]: d["kind"] for d in db.list_deposits(connection, self.business)}
            self.assertEqual(kinds[ids[0]], "Cash / ATM")
            self.assertEqual(kinds[ids[1]], "Mobile / check")
            self.assertEqual(kinds[ids[2]], "Wire / ACH")
            self.assertNotIn(outgoing, kinds)
            done = db.classify_deposits(connection, business_id=self.business,
                                        transaction_ids=[ids[0], ids[1], outgoing],
                                        treatment="Owner contribution", counterparty="Murali")
            self.assertEqual(done, 2)  # the debit is never touched
            rows = {r["id"]: r for r in db.list_transactions(connection, self.business)}
            self.assertEqual(rows[ids[0]]["treatment"], "Owner contribution")
            self.assertEqual(rows[ids[0]]["counterparty"], "Murali")
            self.assertEqual(rows[outgoing]["status"], "needs_review")
            with self.assertRaises(ValueError):
                db.classify_deposits(connection, business_id=self.business, transaction_ids=ids,
                                     treatment="Expense")


    def test_transfer_prefill_and_deposits_in_statement_log(self):
        with db.connect(self.path) as connection:
            other = db.get_or_create_account(connection, self.business, "Savings", "savings")
            db.insert_transaction(
                connection, business_id=self.business, account_id=other, transaction_date="2026-04-18",
                posting_date=None, description="Check #158", source_amount=-9000, signed_amount=-9000)
            dep, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account, transaction_date="2026-04-20",
                posting_date=None, description="ATM DEPOSIT", source_amount=9000, signed_amount=9000)
            guess = db.suggest_transfer_counterpart(connection, self.business, dep)
            self.assertEqual(guess["related_account_id"], other)
            self.assertIn("Matching", guess["reason"])
            db.classify_deposits(connection, business_id=self.business, transaction_ids=[dep],
                                 treatment="Transfer", fill_transfer_from_records=True)
            row = connection.execute("SELECT related_account_id, counterparty FROM transactions WHERE id=?", (dep,)).fetchone()
            self.assertEqual((row["related_account_id"], row["counterparty"]), (other, "Savings"))
            self.assertEqual(db.suggest_deposit_check_details(connection, self.business, dep)["treatment"], "Transfer")
            later, _, _ = db.insert_transaction(
                connection, business_id=self.business, account_id=self.account, transaction_date="2026-08-02",
                posting_date=None, description="ATM DEPOSIT", source_amount=700, signed_amount=700)
            self.assertEqual(db.suggest_transfer_counterpart(connection, self.business, later)["related_account_id"], other)
            db.confirm_deposit_checks(
                connection, business_id=self.business, account_id=self.account, transaction_id=later,
                bank_name="Bank", account_last4="1234",
                deposited_checks=[{"check_number": "55", "payer": "Acme", "amount": 700}],
                category_id=None, treatment="Revenue")
            log = db.list_statement_log(connection, self.business)
            self.assertEqual(len(log), 1)
            self.assertEqual((log[0]["deposits_reconciled"], log[0]["deposit_total"], log[0]["status"]),
                             (1, 700.0, "Deposits only"))
            rows = db.statement_log_rows(connection, self.business)
            self.assertEqual([(r["direction"], r["check_number"], r["amount"]) for r in rows], [("deposit", "55", 700.0)])
            # last-transaction details for a Transfer selection come from the bank transaction's counterparty
            last = db.last_deposit_details(connection, self.business, treatment="Transfer", exclude_transaction_id=None)
            self.assertEqual(last["payer"], "Savings")
            self.assertIsNone(db.last_deposit_details(connection, self.business, treatment="Transfer",
                                                      exclude_transaction_id=dep))


    def test_parties_list_rename_and_merge(self):
        with db.connect(self.path) as connection:
            ids = []
            for day, amount, treatment, party in [
                    ("2026-03-01", -4000, "Loan receivable", "Colina Tech Solutions"),
                    ("2026-04-01", 1000, "Receivable repayment", "Colina Tech Solutions LLC"),
                    ("2026-05-01", 5000, "Loan draw", "Bank Lender")]:
                new, _, _ = db.insert_transaction(
                    connection, business_id=self.business, account_id=self.account, transaction_date=day,
                    posting_date=None, description=f"TXN {day}", source_amount=amount, signed_amount=amount)
                db.update_transaction_classification(connection, new, category_id=None, treatment=treatment)
                connection.execute("UPDATE transactions SET counterparty = ? WHERE id = ?", (party, new))
                ids.append(new)
            parties = {p["party"]: p for p in db.list_parties(connection, self.business)}
            colina = parties["Colina Tech Solutions LLC"]
            self.assertEqual((colina["owed_to_us"], len(colina["spellings"]), colina["transactions"]), (3000.0, 2, 2))
            self.assertEqual(parties["Bank Lender"]["we_owe"], 5000.0)
            counts = db.rename_party(connection, business_id=self.business,
                                     old_names=colina["spellings"], new_name="  Colina   Tech Solutions LLC ")
            self.assertEqual(counts["transactions"], 2)
            merged = [p for p in db.list_parties(connection, self.business) if "Colina" in p["party"]]
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["spellings"], ["Colina Tech Solutions LLC"])
            self.assertEqual(len(db.party_activity(connection, self.business, ["Colina Tech Solutions LLC"])["transactions"]), 2)
            with self.assertRaises(ValueError):
                db.rename_party(connection, business_id=self.business, old_names=["Bank Lender"], new_name=" ")

    def test_personal_tax_prep_items(self):
        with db.connect(self.path) as connection:
            charity_id = db.add_personal_tax_item(
                connection, tax_year=2026, category="Charity", document_type="Charity receipt",
                name="UNICEF", amount=250, status="Received", notes="Online receipt")
            db.add_personal_tax_item(
                connection, tax_year=2025, category="Employment income", document_type="W-2",
                name="Johns Hopkins", amount=100000, status="Entered")
            items = db.list_personal_tax_items(connection, tax_year=2026)
            self.assertEqual(len(items), 1)
            self.assertEqual((items[0]["name"], items[0]["amount"]), ("UNICEF", 250.0))
            self.assertTrue(db.update_personal_tax_item(
                connection, item_id=charity_id, tax_year=2026, category="Charity",
                document_type="Charity receipt", name="UNICEF USA", amount=275,
                status="Entered", notes="Final receipt"))
            updated = db.list_personal_tax_items(connection, tax_year=2026)[0]
            self.assertEqual((updated["name"], updated["amount"], updated["status"]),
                             ("UNICEF USA", 275.0, "Entered"))
            self.assertTrue(db.delete_personal_tax_item(connection, item_id=charity_id))
            self.assertEqual(db.list_personal_tax_items(connection, tax_year=2026), [])
            with self.assertRaises(ValueError):
                db.add_personal_tax_item(
                    connection, tax_year=2026, category="Charity", document_type="Charity receipt",
                    name="", amount=10)


    def test_loan_exclusion_and_vendor_reports(self):
        with db.connect(self.path) as connection:
            def add(day, amount, treatment, party=None, desc=None, category=None):
                tid, _, _ = db.insert_transaction(
                    connection, business_id=self.business, account_id=self.account, transaction_date=day,
                    posting_date=None, description=desc or f"TXN {day} {amount}", source_amount=amount, signed_amount=amount)
                db.update_transaction_classification(connection, tid, category_id=category, treatment=treatment)
                if party:
                    connection.execute("UPDATE transactions SET counterparty = ? WHERE id = ?", (party, tid))
                return tid
            add("2026-01-05", -4000, "Loan receivable", "Colina Tech Solutions")
            add("2026-02-05", 1000, "Receivable repayment", "Colina Tech Solutions LLC")
            add("2026-03-05", 5000, "Loan draw", "Bank Lender")
            add("2026-03-06", 500, "Transfer")
            add("2026-03-07", 250, "Owner contribution")
            add("2026-04-01", 900, "Revenue", "Acme Corp")
            add("2026-04-02", -300, "Expense", None, "DIGITALOCEAN.COM 123", self.category)
            add("2026-04-03", 40, "Expense refund", None, "DIGITALOCEAN.COM 456", self.category)
            report = {r["party"]: r for r in db.loan_report(connection, self.business)}
            self.assertEqual(report["Colina Tech Solutions LLC"]["owed_to_us"], 3000.0)
            self.assertEqual(report["Bank Lender"]["we_owe"], 5000.0)
            self.assertEqual(len(db.loan_ledger(connection, self.business)), 3)
            self.assertEqual(len(db.loan_report(connection, self.business, "2026-02-01", "2026-12-31")), 2)
            reasons = sorted(r["reason"] for r in db.excluded_from_pnl(connection, self.business))
            self.assertEqual(reasons, ["Internal transfer", "Loan made", "Loan received", "Loan repayment received",
                                       "Owner contribution"])
            vendors = {r["party"]: r for r in db.vendor_report(connection, self.business)}
            self.assertEqual(vendors["Acme Corp"]["revenue"], 900.0)
            digital = next(v for name, v in vendors.items() if "Digitalocean" in name)
            self.assertEqual((digital["expense"], digital["transactions"]), (260.0, 2))
            self.assertEqual(db.vendor_report(connection, self.business, "2026-05-01", "2026-12-31"), [])


    def test_margin_mapping(self):
        with db.connect(self.path) as connection:
            def add(day, amount, treatment, party):
                tid, _, _ = db.insert_transaction(
                    connection, business_id=self.business, account_id=self.account, transaction_date=day,
                    posting_date=None, description=f"TXN {day} {amount} {party}", source_amount=amount, signed_amount=amount)
                db.update_transaction_classification(connection, tid, category_id=None, treatment=treatment)
                connection.execute("UPDATE transactions SET counterparty = ? WHERE id = ?", (party, tid))
            add("2026-01-10", 10000, "Revenue", "Acme Corp")
            add("2026-02-10", 5000, "Revenue", "Globex")
            add("2026-01-15", -6000, "Expense", "Consultant One")
            add("2026-02-15", -1500, "Expense", "Consultant Two")
            add("2026-03-15", -200, "Expense", "Random Vendor")
            report = db.margin_report(connection, self.business)
            self.assertTrue(all(not c["mapped"] for c in report["customers"]))
            self.assertEqual(len(report["unmapped_expenses"]), 3)
            db.set_margin_links(connection, business_id=self.business, revenue_party="Acme Corp",
                                expense_parties=["Consultant One", "Consultant Two"])
            report = db.margin_report(connection, self.business)
            acme = next(c for c in report["customers"] if c["customer"] == "Acme Corp")
            self.assertEqual((acme["revenue"], acme["mapped_expense"], acme["margin"], acme["margin_pct"]),
                             (10000.0, 7500.0, 2500.0, 25.0))
            self.assertEqual([u["party"] for u in report["unmapped_expenses"]], ["Random Vendor"])
            # an expense company belongs to one revenue company: re-mapping moves it
            db.set_margin_links(connection, business_id=self.business, revenue_party="Globex",
                                expense_parties=["Consultant Two"])
            report = db.margin_report(connection, self.business)
            self.assertEqual({c["customer"]: c["mapped_expense"] for c in report["customers"]},
                             {"Acme Corp": 6000.0, "Globex": 1500.0})
            # period filter
            feb = db.margin_report(connection, self.business, "2026-02-01", "2026-02-28")
            self.assertEqual({c["customer"]: c["revenue"] for c in feb["customers"]}["Globex"], 5000.0)
            # renaming a party carries its mappings along
            db.rename_party(connection, business_id=self.business, old_names=["Acme Corp"], new_name="Acme Corporation")
            self.assertEqual(db.list_margin_links(connection, self.business)[0]["revenue_party"], "Acme Corporation")
            with self.assertRaises(ValueError):
                db.set_margin_links(connection, business_id=self.business, revenue_party="Globex", expense_parties=["globex"])
            link_ids = [l["id"] for l in db.list_margin_links(connection, self.business)]
            self.assertEqual(db.delete_margin_links(connection, self.business, link_ids), 2)

    def test_edit_and_delete_learned_rule(self):
        with db.connect(self.path) as connection:
            rule_id, _ = db.learn_rule(connection, business_id=self.business, account_id=self.account,
                                       pattern="ACME PAYMENT", category_id=None, treatment="Expense", apply_existing=False)
            other_id, _ = db.learn_rule(connection, business_id=self.business, account_id=self.account,
                                        pattern="GLOBEX", category_id=None, treatment="Expense", apply_existing=False)
            db.update_rule(connection, rule_id, pattern="acme pay", category_id=None, treatment="Revenue",
                           priority=200, active=False)
            row = next(r for r in db.list_rules(connection, self.business) if r["id"] == rule_id)
            self.assertEqual((row["treatment"], row["priority"], row["active"]), ("Revenue", 200, 0))
            self.assertEqual(row["pattern"], db.normalize_description("acme pay"))
            with self.assertRaises(ValueError):
                db.update_rule(connection, other_id, pattern="acme pay", category_id=None, treatment="Expense")
            db.delete_rule(connection, rule_id)
            self.assertEqual([r["id"] for r in db.list_rules(connection, self.business)], [other_id])

    def test_loan_direction_guard(self):
        with db.connect(self.path) as connection:
            self.assertIsNotNone(db.loan_direction_error(4400, "Principal repayment"))
            self.assertIsNotNone(db.loan_direction_error(-10, "Loan draw"))
            self.assertIsNone(db.loan_direction_error(4400, "Receivable repayment"))
            # a loan rule must not capture money moving the other way
            db.learn_rule(connection, business_id=self.business, account_id=self.account, pattern="MOBILE DEPOSIT",
                          category_id=None, treatment="Loan draw", apply_existing=False)
            credit = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-01", posting_date=None, description="MOBILE DEPOSIT", source_amount=50,
                signed_amount=50)
            debit = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-02", posting_date=None, description="MOBILE DEPOSIT", source_amount=-50,
                signed_amount=-50)
            self.assertTrue(credit[2])
            self.assertFalse(debit[2])
            # a wrong-direction entry is found and can be corrected
            connection.execute("UPDATE transactions SET treatment = 'Principal repayment' WHERE id = ?", (credit[0],))
            problems = db.loan_direction_problems(connection, self.business)
            self.assertEqual([p["id"] for p in problems], [credit[0]])
            with self.assertRaises(ValueError):
                db.fix_loan_rows(connection, self.business, [{"id": credit[0], "treatment": "Principal repayment"}])
            db.fix_loan_rows(connection, self.business,
                             [{"id": credit[0], "treatment": "Receivable repayment", "counterparty": "Colina"}])
            self.assertEqual(db.loan_direction_problems(connection, self.business), [])
            # the owner's own money filed as a loan is flagged and moves out of the loan books
            out = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-05", posting_date=None, description="TRANSFER TO CHK 9651", source_amount=-70,
                signed_amount=-70, treatment="Loan receivable", status="confirmed")
            connection.execute("UPDATE transactions SET counterparty = 'Owner contribution' WHERE id = ?", (out[0],))
            owner = [p for p in db.loan_direction_problems(connection, self.business) if p["id"] == out[0]][0]
            self.assertEqual(owner["suggested"], "Owner draw")
            db.fix_loan_rows(connection, self.business, [{"id": out[0], "treatment": "Owner draw", "counterparty": "Owner"}])
            self.assertEqual([r["party"] for r in db.loan_report(connection, self.business)], ["Colina"])
            self.assertIsNotNone(db.loan_direction_error(-70, "Owner contribution"))

    def test_per_business_categories_copy_and_split(self):
        with db.connect(self.path) as connection:
            other = db.get_or_create_business(connection, "Other Business")
            first = db.get_or_create_category(connection, self.business, "Legal expense", "Expense")
            second = db.get_or_create_category(connection, other, "legal EXPENSE", "Expense")
            self.assertNotEqual(first, second)
            self.assertNotIn("Legal expense", {c["name"] for c in db.list_categories(connection, other)} - {"legal EXPENSE"})
            with self.assertRaises(ValueError):
                db.update_category(connection, db.get_or_create_category(connection, self.business, "Rent", "Expense"),
                                   name="Legal Expense", default_treatment="Expense", active=True)
            # copying never overwrites and also copies bank-text rules with their category
            self.assertEqual(db.copy_categories(connection, self.business, other, ["Legal expense", "Rent"]),
                             {"copied": 1, "skipped": 1})
            now = "2026-01-01"
            connection.execute("INSERT INTO vendors(business_id, name, match_pattern, category_id, treatment, created_at, updated_at) "
                               "VALUES (?, 'Acme', 'ACME', ?, 'Expense', ?, ?)", (self.business, first, now, now))
            self.assertEqual(db.copy_bank_text_rules(connection, self.business, other), {"copied": 1, "skipped": 0})
            self.assertEqual(db.copy_bank_text_rules(connection, self.business, other), {"copied": 0, "skipped": 1})
            # a legacy shared category is split so each business owns its copy
            txn = db.insert_transaction(connection, business_id=other, account_id=db.get_or_create_account(
                connection, other, "Chk", "checking"), transaction_date="2026-04-01", posting_date=None,
                description="X", source_amount=-5, signed_amount=-5, category_id=first, treatment="Expense", status="confirmed")
            db.set_setting(connection, "categories_split_v1", "")
            db.split_categories_by_business(connection)
            owner = connection.execute("SELECT c.business_id FROM transactions t JOIN categories c ON c.id = t.category_id "
                                       "WHERE t.id = ?", (txn[0],)).fetchone()[0]
            self.assertEqual(owner, other)
            # rule learning skips one-off and loan rules; cleanup finds the old ones
            self.assertFalse(db.should_learn_rule("CHECK 140", "Expense"))
            self.assertFalse(db.should_learn_rule("MOBILE DEPOSIT", "Loan draw"))
            self.assertTrue(db.should_learn_rule("COLINA TECH ZELLE", "Receivable repayment"))
            self.assertTrue(db.should_learn_rule("DIGITALOCEAN", "Expense"))
            db.learn_rule(connection, business_id=self.business, account_id=None, pattern="CHECK 140",
                          category_id=None, treatment="Expense", apply_existing=False)
            db.learn_rule(connection, business_id=self.business, account_id=None, pattern="DEPOSIT",
                          category_id=None, treatment="Loan draw", apply_existing=False)
            db.learn_rule(connection, business_id=self.business, account_id=None, pattern="DIGITALOCEAN",
                          category_id=None, treatment="Expense", apply_existing=False)
            found = db.rule_cleanup_candidates(connection, self.business)
            self.assertEqual({r["pattern"] for r in found}, {"CHECK 140", "DEPOSIT"})
            self.assertEqual(db.delete_rules(connection, self.business, [r["id"] for r in found]), 2)

    def test_split_log_and_revert(self):
        with db.connect(self.path) as connection:
            rev = db.get_or_create_category(connection, self.business, "Services", "Revenue")
            txn = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-06-01", posting_date=None, description="MOBILE DEPOSIT", source_amount=1000,
                signed_amount=1000, status="needs_review")[0]
            before = {r["id"]: r for r in db.account_summaries(connection, self.business)}
            with self.assertRaises(ValueError):
                db.split_transaction(connection, business_id=self.business, transaction_id=txn,
                                     lines=[{"amount": 600, "treatment": "Revenue"}, {"amount": 300, "treatment": "Revenue"}])
            with self.assertRaises(ValueError):  # money in cannot be a loan we made
                db.split_transaction(connection, business_id=self.business, transaction_id=txn,
                                     lines=[{"amount": 600, "treatment": "Loan receivable"}, {"amount": 400, "treatment": "Revenue"}])
            ids = db.split_transaction(connection, business_id=self.business, transaction_id=txn, lines=[
                {"amount": 600, "category_id": rev, "treatment": "Revenue", "counterparty": "Acme"},
                {"amount": 400, "treatment": "Receivable repayment", "counterparty": "Colina"}])
            self.assertEqual(len(ids), 2)
            parent = db.get_transaction(connection, txn)
            self.assertEqual((parent["status"], parent["treatment"]), ("split", "Excluded"))
            self.assertEqual({r["id"]: r for r in db.account_summaries(connection, self.business)}, before)
            report = {r["category"]: r for r in db.category_summary(connection, self.business)}
            self.assertEqual(report["Services"]["revenue"], 600)
            listed = [r["id"] for r in db.list_unreconciled_deposits(connection, self.business, self.account, checks_only=False)]
            self.assertIn(txn, listed)  # the original stays available for attaching check images
            self.assertFalse(set(ids) & set(listed))
            self.assertNotIn(txn, [r["id"] for r in db.excluded_from_pnl(connection, self.business)])
            with self.assertRaises(ValueError):
                db.update_transaction_classification(connection, txn, category_id=None, treatment="Revenue")
            with self.assertRaises(ValueError):  # locked until the split is reverted
                db.split_transaction(connection, business_id=self.business, transaction_id=txn, lines=[
                    {"amount": 500, "treatment": "Revenue"}, {"amount": 500, "treatment": "Revenue"}])
            with self.assertRaises(ValueError):
                db.set_transaction_counterparty(connection, business_id=self.business, transaction_id=txn, counterparty="X")
            self.assertEqual(len(db.get_split_lines(connection, txn)), 2)
            self.assertEqual(db.revert_split(connection, business_id=self.business, transaction_id=txn), 2)
            restored = db.get_transaction(connection, txn)
            self.assertEqual((restored["status"], restored["treatment"]), ("needs_review", "Needs review"))
            self.assertEqual(db.get_split_lines(connection, txn), [])
            self.assertEqual([r["action"] for r in db.list_split_log(connection, self.business)],
                             ["revert", "split"])

    def test_multi_check_deposit_needs_split(self):
        with db.connect(self.path) as connection:
            txn = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-07-01", posting_date=None, description="MOBILE DEPOSIT", source_amount=700,
                signed_amount=700, status="needs_review")[0]
            db.confirm_deposit_checks(connection, business_id=self.business, account_id=self.account,
                transaction_id=txn, bank_name="B", account_last4="1", category_id=None, treatment=None, needs_split=True,
                deposited_checks=[{"check_number": "11", "payer": "Acme", "amount": 500},
                                  {"check_number": "CASH-1-2", "payer": "", "amount": 200, "memo": "Cash deposit"}])
            row = db.get_transaction(connection, txn)
            self.assertEqual((row["status"], row["treatment"], row["notes"]), ("needs_review", "Needs review", "Needs split: 2 checks"))
            self.assertEqual(len(db.deposit_check_lines(connection, txn)), 2)
            register = db.list_check_register(connection, self.business)
            self.assertEqual({r["lines_on_transaction"] for r in register if r["transaction_id"] == txn}, {2})
            self.assertEqual([r for r in db.list_transactions(connection, self.business) if r["id"] == txn][0]["linked_checks"], 2)

    def test_attachments(self):
        with db.connect(self.path) as connection:
            txn = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-08-01", posting_date=None, description="STAPLES", source_amount=-20,
                signed_amount=-20)[0]
            first = db.add_attachment(connection, business_id=self.business, transaction_id=txn,
                                      file_name="receipt.pdf", data=b"%PDF-1.4 test")
            self.assertEqual(db.add_attachment(connection, business_id=self.business, transaction_id=txn,
                                               file_name="receipt.pdf", data=b"%PDF-1.4 test"), first)
            with self.assertRaises(ValueError):
                db.add_attachment(connection, business_id=self.business, transaction_id=txn, file_name="x.exe", data=b"1")
            with self.assertRaises(ValueError):
                db.add_attachment(connection, business_id=self.business + 9, transaction_id=txn, file_name="a.pdf", data=b"1")
            self.assertEqual([a["file_name"] for a in db.list_attachments(connection, self.business, txn)], ["receipt.pdf"])
            self.assertEqual(db.get_attachment_data(connection, self.business, first), b"%PDF-1.4 test")
            self.assertIsNone(db.get_attachment_data(connection, self.business + 9, first))
            self.assertEqual([r for r in db.list_transactions(connection, self.business) if r["id"] == txn][0]["attachments"], 1)
            self.assertTrue(db.delete_attachment(connection, self.business, first))
            db.add_attachment(connection, business_id=self.business, transaction_id=txn, file_name="a.pdf", data=b"1")
            db.add_attachment(connection, business_id=self.business, transaction_id=txn, file_name="b.pdf", data=b"22")
            self.assertEqual(db.clear_attachments(connection, self.business, txn), 2)
            self.assertEqual(db.list_attachments(connection, self.business, txn), [])

    def test_document_parsing_and_matching(self):
        from books import documents
        parsed = documents.parse_document("ACME Office Supplies Inc\nInvoice # INV-20418\nDate: 03/14/2026\nSubtotal $20.00\nTax $1.60\nTotal $21.60")
        self.assertEqual((parsed["total"], parsed["dates"], parsed["invoice"], parsed["vendor"]),
                         (21.6, ["2026-03-14"], "INV-20418", "ACME Office Supplies Inc"))
        self.assertFalse(documents.parse_document("")["has_text"])
        with db.connect(self.path) as connection:
            near = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-15", posting_date=None, description="ACME OFFICE SUPPLIES", source_amount=-21.6,
                signed_amount=-21.6)[0]
            db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2025-01-02", posting_date=None, description="OTHER", source_amount=-21.6, signed_amount=-21.6)
            found = documents.match_candidates(connection, self.business, parsed)
            self.assertEqual(found[0]["id"], near)
            self.assertGreaterEqual(found[0]["score"], 5)

    def test_loan_notes(self):
        with db.connect(self.path) as connection:
            txn = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-05-01", posting_date=None, description="LOAN OUT", source_amount=-900,
                signed_amount=-900, treatment="Loan receivable", status="confirmed")
            row = db.loan_ledger(connection, self.business)[0]
            self.assertEqual((row["kind"], row["id"], row["notes"]), ("transaction", txn[0], ""))
            self.assertEqual(db.set_loan_notes(connection, self.business,
                             [{"kind": "transaction", "id": txn[0], "notes": "  Working   capital for payroll "}]), 1)
            self.assertEqual(db.loan_ledger(connection, self.business)[0]["notes"], "Working capital for payroll")
            # another business cannot edit it
            self.assertEqual(db.set_loan_notes(connection, self.business + 99,
                             [{"kind": "transaction", "id": txn[0], "notes": "x"}]), 0)


    def test_summary_and_mileage(self):
        from books import mileage, summary
        with db.connect(self.path) as connection:
            for day, text, amount, treatment in (("2026-02-01", "CLIENT PAY", 1000, "Revenue"), ("2026-02-02", "REFUND", -100, "Revenue refund"),
                                                 ("2026-02-03", "HOST", -40, "Expense"), ("2026-02-04", "TO SAV", -500, "Transfer")):
                tid, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                    transaction_date=day, posting_date=None, description=text, source_amount=amount, signed_amount=amount)
                db.classify_transaction(connection, tid, category_id=self.category if treatment == "Expense" else None,
                                        treatment=treatment)
            data = summary.preliminary(connection, self.business, "2026-01-01", "2026-12-31")
            self.assertEqual((data["revenue_total"], data["expense_total"], data["net"]), (900, 40, 860))
            self.assertEqual(data["excluded"][0]["amount"], 500)
            mileage.add_trip(connection, self.business, trip_date="2026-03-01", miles=10, purpose="Bank")
            mileage.add_trip(connection, self.business, trip_date="2026-03-02", miles=5.5, kind="Charity")
            with self.assertRaises(ValueError):
                mileage.add_trip(connection, self.business, trip_date="2026-03-02", miles=0)
            rates = mileage.get_rates(connection, 2026)
            self.assertEqual(rates["Business"], 0.70)
            mileage.set_rate(connection, 2026, "Business", 0.8)
            trips = mileage.list_trips(connection, self.business, 2026)
            lines = mileage.summarize(trips, mileage.get_rates(connection, 2026))
            self.assertEqual(lines[0]["Deduction"], 8.0)
            self.assertTrue(summary.summary_workbook(connection, self.business, "Test", "2026-01-01", "2026-12-31", 2026)[:2] == b"PK")
            parsed, bad = mileage.parse_pasted("Trip Date\tPurpose\tMiles\n04/08/26\tWeekly round trip\t18\n04/15/26\tWeekly round trip\t18\nTotal miles\t\t36\nxx\tbad\t1")
            self.assertEqual([(t["trip_date"], t["purpose"], t["miles"]) for t in parsed],
                             [("2026-04-08", "Weekly round trip", 18.0), ("2026-04-15", "Weekly round trip", 18.0)])
            self.assertEqual(len(bad), 1)
            dates = mileage.repeat_dates("2026-04", "2026-10", 2)
            self.assertEqual((dates[0], dates[-1], len(dates)), ("2026-04-01", "2026-10-28", 31))
            self.assertEqual(mileage.add_trips(connection, self.business, parsed), (2, 0))
            self.assertEqual(mileage.add_trips(connection, self.business, parsed), (0, 2))
            self.assertEqual(mileage.delete_trips(connection, self.business, [trips[0]["id"]]), 1)

    def test_ask_search(self):
        from datetime import date
        from books import ask
        with db.connect(self.path) as connection:
            for day, text, amount in (("2026-03-05", "ZELLE TO ALGEBRA IT LLC", -6000), ("2026-03-20", "HOSTING CO", -50),
                                      ("2026-04-02", "ZELLE TO ALGEBRA IT LLC", -4000), ("2026-04-09", "ACME DEPOSIT", 9000)):
                tid, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                    transaction_date=day, posting_date=None, description=text, source_amount=amount, signed_amount=amount)
                if amount < 0:
                    db.classify_transaction(connection, tid, category_id=self.category, treatment="Expense")
            today = date(2026, 5, 15)
            q = ask.parse("algebra it payments over 5000 2026", ["Hosting"], [], today)
            rows = ask.run(connection, q, self.business)
            self.assertEqual([r["Amount"] for r in rows], [-6000])
            q = ask.parse("algebraIT by month", [], [], today)
            self.assertEqual({g["Month"]: g["Out"] for g in ask.group(ask.run(connection, q, self.business), "Month")},
                             {"2026-03": 6000, "2026-04": 4000})
            q = ask.parse("april", [], [], today)
            self.assertEqual((q.start, q.end), ("2026-04-01", "2026-04-30"))
            self.assertEqual(len(ask.run(connection, q, self.business)), 2)
            q = ask.parse("hosting last month", ["Hosting"], [], today)
            self.assertEqual((q.category, q.start), ("Hosting", "2026-04-01"))
            q = ask.parse("$9,000", [], [], today)
            self.assertEqual(ask.totals(ask.run(connection, q, self.business))["in"], 9000)
            for day, text, amount, treatment in (("2026-05-01", "LOC ADVANCE", 8000, "Loan draw"),
                                                 ("2026-05-02", "TO SAVINGS", -500, "Transfer")):
                tid, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                    transaction_date=day, posting_date=None, description=text, source_amount=amount, signed_amount=amount)
                db.classify_transaction(connection, tid, category_id=None, treatment=treatment)
            self.assertEqual([r["Amount"] for r in ask.run(connection, ask.parse("loan draws 2026", [], [], today), self.business)], [8000])
            q = ask.parse("loan draw", ["Loan"], [], today)
            self.assertEqual((q.treatments, q.category), (["Loan draw"], ""))
            self.assertEqual([r["Amount"] for r in ask.run(connection, ask.parse("internal transfers", [], [], today), self.business)], [-500])
            self.assertEqual(db.owner_equity(connection, [self.business]), {"contributions": 0.0, "draws": 0.0})
            tid, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-06-01", posting_date=None, description="OWNER IN", source_amount=700, signed_amount=700)
            db.classify_transaction(connection, tid, category_id=None, treatment="Owner contribution")
            self.assertEqual(db.owner_equity(connection, [self.business], "2026-01-01", "2026-12-31")["contributions"], 700)
            self.assertEqual(ask.run(connection, ask.parse("nothing like this", [], [], today), self.business), [])

    def test_staff_payments_and_company_revenue(self):
        from books import staff
        with db.connect(self.path) as connection:
            staff.add_payment(connection, self.business, name="Ann Lee", month="2026-03", amount=4000, note="chk 101")
            staff.add_payment(connection, self.business, name="ann lee", month="2026-03", amount=500)
            staff.add_payment(connection, self.business, name="Cy Co LLC", month="2026-03", amount=2500)
            with self.assertRaises(ValueError):
                staff.add_payment(connection, self.business, name="", month="2026-03", amount=5)
            with self.assertRaises(ValueError):
                staff.add_payment(connection, self.business, name="Ann Lee", month="2026-03", amount=0)
            self.assertEqual(len(staff.list_staff(connection, self.business)), 2)
            self.assertEqual(staff.paid_by_month(connection, self.business)["2026-03"], 7000)
            out, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-31", posting_date=None, description="ZELLE PAYMENT TO CY CO LLC",
                source_amount=-2500, signed_amount=-2500)
            found = staff.payment_suggestions(connection, self.business, "2026-03")
            self.assertEqual(found[0]["transaction"]["id"], out)
            self.assertEqual(found[0]["payment"]["staff"], "Cy Co LLC")
            payroll = db.get_or_create_category(connection, self.business, "Payroll", "Expense")
            with self.assertRaises(ValueError):
                staff.link_payment(connection, self.business, found[0]["payment"]["id"] - 1, out)
            staff.link_payment(connection, self.business, found[0]["payment"]["id"], out, category_id=payroll)
            self.assertEqual(db.get_transaction(connection, out)["counterparty"], "Cy Co LLC")
            self.assertEqual(staff.payment_suggestions(connection, self.business, "2026-03"), [])
            first, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-10", posting_date=None, description="WIRE FROM ACME CORP INV 1",
                source_amount=9000, signed_amount=9000)
            second, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-04-02", posting_date=None, description="ACME CORP PAYMENT",
                source_amount=1000, signed_amount=1000)
            db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-11", posting_date=None, description="OTHER CLIENT",
                source_amount=50, signed_amount=50)
            found_rev = staff.revenue_candidates(connection, self.business, "Acme Corp", "2026-03-01", "2026-04-30")
            self.assertEqual([r["id"] for r in found_rev], [first, second])
            staff.save_revenue_picks(connection, self.business, "Acme Corp", [first, second], [first])
            totals = staff.revenue_by_month(connection, self.business)
            self.assertEqual([(r["month"], r["total"]) for r in totals], [("2026-03", 9000)])
            # picked by another company: hidden from a different company's list
            self.assertEqual(staff.revenue_candidates(connection, self.business, "Wire From", "2026-03-01", "2026-03-31"), [])
            found_names = staff.name_matches(connection, self.business, "Ann Lee", "2026-03")
            self.assertEqual(found_names, [])
            ann_check, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-03-15", posting_date=None, description="ZELLE PAYMENT TO ANN LEE FOR MARCH",
                source_amount=-1200, signed_amount=-1200)
            self.assertEqual([t["id"] for t in staff.name_matches(connection, self.business, "ann lee", "2026-03")], [ann_check])
            self.assertEqual(staff.name_matches(connection, self.business, "Ann Lee", "2026-04"), [])
            april_pay, _, _ = db.insert_transaction(connection, business_id=self.business, account_id=self.account,
                transaction_date="2026-04-03", posting_date=None, description="CHECK PAID ANN LEE",
                source_amount=-300, signed_amount=-300)
            self.assertEqual([t["id"] for t in staff.name_matches(connection, self.business, "Ann Lee", "2026-03")], [ann_check])
            self.assertEqual([t["id"] for t in staff.name_matches(connection, self.business, "Ann Lee", "2026-04")], [april_pay])
            self.assertEqual(staff.add_payments_from_transactions(connection, self.business, name="Ann Lee",
                                                                  month="2026-03", transaction_ids=[ann_check]), 1)
            self.assertEqual(staff.name_matches(connection, self.business, "Ann Lee", "2026-03"), [])
            self.assertEqual(staff.copy_payments(connection, self.business, "2026-03", "2026-04"), 4)
            self.assertEqual(staff.copy_payments(connection, self.business, "2026-03", "2026-04"), 0)
            self.assertEqual([p["transaction_id"] for p in staff.list_payments(connection, self.business, "2026-04")].count(None), 4)
            with self.assertRaises(ValueError):
                staff.copy_payments(connection, self.business, "2026-03", "2026-03")
            self.assertEqual(staff.previous_month("2026-01"), "2025-12")
            result = staff.autofill_payments(connection, self.business, "2026-04")
            self.assertEqual((result["added"], result["no_match"]), (1, ["Cy Co LLC"]))
            self.assertEqual(staff.autofill_payments(connection, self.business, "2026-04")["added"], 0)
            result = staff.autofill_revenue(connection, self.business, "2026-04")
            self.assertEqual((result["added"], result["no_match"]), (1, []))
            self.assertEqual(staff.autofill_revenue(connection, self.business, "2026-04")["added"], 0)
            self.assertEqual(sorted((r["month"], r["total"]) for r in staff.revenue_by_month(connection, self.business)),
                             [("2026-03", 9000), ("2026-04", 1000)])
            self.assertEqual(staff.months_between("2025-11", "2026-02"), ["2025-11", "2025-12", "2026-01", "2026-02"])
            with self.assertRaises(ValueError):
                staff.months_between("2026-03", "2026-01")
            detail = staff.paid_detail(connection, self.business, "2026-03", "2026-04", ["ann lee"])
            self.assertEqual({(r["name"], r["month"]) for r in detail}, {("Ann Lee", "2026-03"), ("Ann Lee", "2026-04")})
            self.assertEqual([r["total"] for r in staff.revenue_detail(connection, self.business, "2026-03", "2026-03", ["Acme Corp"])], [9000])
            self.assertEqual(staff.revenue_detail(connection, self.business, "2026-03", "2026-03", ["Nobody"]), [])
            summary = staff.summary(connection, self.business, ["2026-03"])[0]
            self.assertEqual((summary["paid"], summary["revenue"], summary["margin"]), (8200, 9000, 800))


if __name__ == "__main__":
    unittest.main()