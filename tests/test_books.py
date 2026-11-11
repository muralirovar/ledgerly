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
