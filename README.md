# Business Books

A local, multi-business transaction review and bookkeeping workspace. It keeps its records in a local SQLite database and exports each business to Excel whenever needed.

The included starter database contains:

- HCCL, imported from the reconciled workbook as confirmed transactions
- Rovar Infotech LLC, imported as transactions needing review
- Three placeholder Rovar line-of-credit accounts

## What it does

- Dashboard for one business or all businesses
- CSV upload, partial upload, and pasted rows
- Duplicate protection and import-batch undo
- Review queue with categories and accounting treatment
- Learns a business/account-specific rule every time a decision is saved
- Tracks line-of-credit draws, principal repayments, interest, and fees separately
- Exports transactions, summaries, accounts, rules, and import logs to Excel
- Supports optional OpenAI or Anthropic keys later without storing keys in the database

## Start with Docker

From this folder:

```bash
docker compose up --build
```

Open <http://localhost:8501>. Records persist in `data/books.db` on the host.

To stop it:

```bash
docker compose down
```

## Start directly with Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Optional API keys

Copy `.env.example` to `.env`, add one or both keys, and restart Docker. Keys remain environment settings and are not written to the bookkeeping database. AI transaction decisions are intentionally not enabled yet; local learned rules are the active classifier.

## Backups

When the app is stopped, copy `data/books.db` to back up everything. Excel exports are reports, while the SQLite file is the live source of truth.
