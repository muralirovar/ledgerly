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


if __name__ == "__main__":
    unittest.main()
