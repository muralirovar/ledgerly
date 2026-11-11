from __future__ import annotations

import os
import re
from html import escape
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from books import ai_config, db, exporter, importers, statements


APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BOOKS_DB_PATH", APP_DIR / "data" / "books.db"))
db.init_db(DB_PATH)

st.set_page_config(page_title="Ledgerly · Business Books", page_icon="◈", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown("""
<style>
  :root {
    --ink: #14233b; --muted: #68758a; --line: #e3e8ef; --paper: #ffffff;
    --canvas: #f4f6f9; --teal: #11847b; --teal-soft: #e8f6f3;
    --gold: #c88723; --gold-soft: #fff4df; --rose: #c05264; --rose-soft: #fdeff1;
  }
  html, body, [class*="css"] {font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
  [data-testid="stAppViewContainer"] {background: var(--canvas); color: var(--ink);}
  header[data-testid="stHeader"] {background:transparent; height:2.2rem;}
  [data-testid="stToolbar"] {visibility:visible;}
  [data-testid="stSidebarCollapseButton"] {
    display:flex !important; visibility:visible !important; opacity:1 !important;
  }
  [data-testid="stExpandSidebarButton"],
  [data-testid="stSidebarCollapsedControl"] {
    display:flex !important; visibility:visible !important; opacity:1 !important;
    position:fixed !important; top:.65rem !important; left:.75rem !important;
    z-index:1000000 !important;
  }
  button[data-testid="stExpandSidebarButton"],
  [data-testid="stSidebarCollapsedControl"] button {
    width:42px !important; height:42px !important; border-radius:11px !important;
    color:#fff !important; background:#142a43 !important;
    border:1px solid rgba(255,255,255,.18) !important;
    box-shadow:0 6px 18px rgba(20,42,67,.22) !important;
  }
  button[data-testid="stExpandSidebarButton"] span {color:#fff !important;}
  body:has([data-testid="stSidebarCollapseButton"] button[aria-expanded="true"])
    button[data-testid="stExpandSidebarButton"] {display:none !important;}
  [data-testid="stMainBlockContainer"] {max-width: 1480px; padding: 2.25rem 3rem 4rem;}
  [data-testid="stSidebar"] {background: linear-gradient(180deg, #12243a 0%, #172f48 58%, #0d3c42 100%); border-right: 0;}
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap: .72rem;}
  [data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {color: #dce7ef;}
  [data-testid="stSidebar"] [role="radiogroup"] {gap: .25rem;}
  [data-testid="stSidebar"] [role="radiogroup"] label {padding: .72rem .85rem; border-radius: 10px; transition: .15s ease;}
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child {display:none;}
  [data-testid="stSidebar"] [role="radiogroup"] label:hover {background: rgba(255,255,255,.08);}
  [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background: rgba(255,255,255,.14); box-shadow: inset 3px 0 0 #5bd0c3;}
  [data-testid="stSidebar"] [data-baseweb="select"] > div {background: rgba(255,255,255,.1); border-color: rgba(255,255,255,.15);}
  [data-testid="stSidebar"] hr {border-color: rgba(255,255,255,.12);}
  .brand {padding: .45rem .2rem 1.15rem; display:flex; align-items:center; gap:.8rem;}
  .brand-mark {width:40px; height:40px; border-radius:12px; display:grid; place-items:center; color:#0c3e40; background:#62d5c8; font-size:1.35rem; font-weight:900; box-shadow:0 8px 24px rgba(0,0,0,.22);}
  .brand-name {color:#fff; font-size:1.1rem; font-weight:760; letter-spacing:-.02em;}
  .brand-sub {color:#91a9b9; font-size:.72rem; text-transform:uppercase; letter-spacing:.12em; margin-top:.1rem;}
  .page-head {margin:.15rem 0 1.6rem;}
  .eyebrow {font-size:.73rem; font-weight:750; color:var(--teal); text-transform:uppercase; letter-spacing:.14em; margin-bottom:.45rem;}
  .page-title {font-family: Georgia, "Times New Roman", serif; font-size:2.35rem; line-height:1.08; color:var(--ink); letter-spacing:-.035em; margin:0;}
  .page-sub {color:var(--muted); font-size:.98rem; margin-top:.55rem; max-width:760px; line-height:1.55;}
  .metric-card {background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:1.15rem 1.2rem; min-height:132px; box-shadow:0 4px 18px rgba(19,37,61,.045); position:relative; overflow:hidden;}
  .metric-card:after {content:""; position:absolute; width:70px; height:70px; border-radius:50%; right:-25px; top:-27px; background:var(--tint);}
  .metric-icon {width:32px; height:32px; border-radius:9px; display:grid; place-items:center; background:var(--tint); color:var(--accent); font-weight:800; margin-bottom:.75rem;}
  .metric-label {font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-weight:720;}
  .metric-value {font-family:Georgia, "Times New Roman", serif; font-size:clamp(1.35rem,2vw,1.75rem); color:var(--ink); letter-spacing:-.03em; margin-top:.2rem; white-space:nowrap;}
  .metric-note {font-size:.78rem; color:var(--muted); margin-top:.25rem;}
  .card {background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:1.25rem 1.35rem; box-shadow:0 4px 18px rgba(19,37,61,.04);}
  .transaction-card {background:linear-gradient(135deg,#142a43,#17464c); color:#fff; border-radius:18px; padding:1.45rem 1.55rem; box-shadow:0 12px 34px rgba(20,42,67,.18); margin:.4rem 0 1rem;}
  .transaction-card .meta {color:#9dc0c4; text-transform:uppercase; letter-spacing:.1em; font-size:.7rem; font-weight:700;}
  .transaction-card .desc {font-size:1.02rem; line-height:1.5; margin:.65rem 0 1rem; color:#f5fafb;}
  .transaction-card .amount {font-family:Georgia,serif; font-size:2rem; letter-spacing:-.02em;}
  .transaction-card .account {color:#b6d7d6; font-size:.84rem; margin-top:.2rem;}
  .section-kicker {font-size:.74rem; text-transform:uppercase; letter-spacing:.11em; color:var(--muted); font-weight:750; margin:1.75rem 0 .65rem;}
  div[data-testid="stForm"] {background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:1.2rem 1.3rem 1.35rem; box-shadow:0 4px 18px rgba(19,37,61,.04);}
  div[data-testid="stDataFrame"] {border:1px solid var(--line); border-radius:14px; overflow:hidden; box-shadow:0 3px 14px rgba(19,37,61,.035);}
  .stButton > button, .stDownloadButton > button {border-radius:10px; min-height:2.65rem; font-weight:680; border:1px solid #d8e0e8; background:#fff; color:var(--ink);}
  .stButton > button:hover, .stDownloadButton > button:hover {border-color:#9fb1c1; color:#0b7069;}
  .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {background:var(--teal); color:#fff; border-color:var(--teal); box-shadow:0 5px 15px rgba(17,132,123,.2);}
  .stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {background:#0b7069; border-color:#0b7069;}
  [data-baseweb="select"] > div, .stTextInput input, .stNumberInput input, .stTextArea textarea {border-radius:10px !important; border-color:#dce3eb !important; background:#fff !important;}
  [data-testid="stAlert"] {border-radius:12px;}
  hr {border-color:var(--line); margin:2rem 0;}
  @media (max-width: 900px) {
    [data-testid="stMainBlockContainer"] {padding:1.5rem 1.1rem 3rem;}
    .page-title{font-size:1.9rem;}
    [data-testid="stHorizontalBlock"] {flex-wrap:wrap; gap:.8rem !important;}
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {min-width:210px; flex:1 1 calc(50% - .8rem) !important; width:auto !important;}
  }
  @media (max-width: 560px) {
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {min-width:100%; flex-basis:100% !important;}
  }
</style>
""", unsafe_allow_html=True)


def money(value: float) -> str:
    return f"${value:,.2f}"


def rerun() -> None:
    st.rerun()


def page_header(title: str, subtitle: str, eyebrow: str = "Workspace") -> None:
    st.markdown(
        f'<div class="page-head"><div class="eyebrow">{escape(eyebrow)}</div>'
        f'<h1 class="page-title">{escape(title)}</h1>'
        f'<div class="page-sub">{escape(subtitle)}</div></div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, note: str, icon: str, tone: str = "teal") -> None:
    colors = {
        "teal": ("#11847b", "#e8f6f3"), "navy": ("#294b72", "#eaf0f7"),
        "gold": ("#b87818", "#fff4df"), "rose": ("#b84e60", "#fdeff1"),
    }
    accent, tint = colors[tone]
    st.markdown(
        f'<div class="metric-card" style="--accent:{accent};--tint:{tint}">'
        f'<div class="metric-icon">{escape(icon)}</div><div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(value)}</div><div class="metric-note">{escape(note)}</div></div>',
        unsafe_allow_html=True,
    )


def section_label(text: str) -> None:
    st.markdown(f'<div class="section-kicker">{escape(text)}</div>', unsafe_allow_html=True)


def go_to(label: str) -> None:
    st.session_state["nav_choice"] = label


def sync_category_treatment(category_key: str, treatment_key: str, defaults: dict[str, str]) -> None:
    selected = st.session_state.get(category_key)
    if selected in defaults:
        st.session_state[treatment_key] = defaults[selected]


def apply_payee_history(history_key: str, payee_key: str, memo_key: str, category_key: str,
                        treatment_key: str, history: dict[str, dict]) -> None:
    item = history.get(st.session_state.get(history_key))
    if not item:
        return
    st.session_state[payee_key] = item["payee"]
    if item.get("memo"):
        st.session_state[memo_key] = item["memo"]
    if item.get("category") and item["category"] in st.session_state.get("_check_category_names", ()):
        st.session_state[category_key] = item["category"]
    if item.get("treatment") and item["treatment"] != "Needs review":
        st.session_state[treatment_key] = item["treatment"]


def go_to_check_image(name: str) -> None:
    st.session_state["active_check_image"] = name


def sync_check_direction(check_type_key: str, category_key: str, treatment_key: str) -> None:
    if st.session_state.get(category_key) == "Uncategorized":
        st.session_state[treatment_key] = (
            "Revenue" if st.session_state.get(check_type_key) == "deposit" else "Expense"
        )


with db.connect(DB_PATH) as connection:
    businesses = db.list_businesses(connection)

st.sidebar.markdown(
    '<div class="brand"><div class="brand-mark">L</div><div><div class="brand-name">Ledgerly</div>'
    '<div class="brand-sub">Business books</div></div></div>', unsafe_allow_html=True)
nav = {
    "▦  Dashboard": "Dashboard", "↗  Revenue & expense": "Revenue & Expense",
    "▣  Tax prep": "Tax Prep",
    "⇧  Import transactions": "Import / Paste",
    "▤  Statements & checks": "Statements & Checks",
    "✓  Review queue": "Review Queue", "≡  All transactions": "Transactions",
    "⌂  Vendors": "Vendors", "⌁  Categories & rules": "Categories & Rules",
    "◇  Accounts & credit": "Accounts & Credit",
    "⚙  Manage business": "Manage Business", "↓  Export & settings": "Export & Settings",
}
if st.session_state.get("nav_choice") not in nav:
    st.session_state["nav_choice"] = "▦  Dashboard"
nav_choice = st.sidebar.radio("Navigation", list(nav), label_visibility="collapsed", key="nav_choice")
page = nav[nav_choice]

if not businesses:
    st.title("Create your first business")
    with st.form("first_business"):
        name = st.text_input("Business name")
        if st.form_submit_button("Create business", type="primary") and name.strip():
            with db.connect(DB_PATH) as connection:
                db.get_or_create_business(connection, name.strip())
            rerun()
    st.stop()

business_by_name = {item["name"]: item for item in businesses}
business_names = list(business_by_name)
with db.connect(DB_PATH) as connection:
    default_business_id = db.get_setting(connection, "default_business_id", "")
default_business_index = next(
    (index for index, name in enumerate(business_names)
     if str(business_by_name[name]["id"]) == default_business_id), 0)
business_name = st.sidebar.selectbox("Business", business_names, index=default_business_index)
business_id = int(business_by_name[business_name]["id"])
st.sidebar.caption("Your records remain on this machine.")

with st.sidebar.expander("Add another business"):
    new_business = st.text_input("New business name", key="new_business")
    if st.button("Add business", width="stretch") and new_business.strip():
        with db.connect(DB_PATH) as connection:
            db.get_or_create_business(connection, new_business.strip())
        rerun()


if page == "Dashboard":
    page_header(f"Good morning — here’s {business_name}",
                "A clean snapshot of revenue, spending, review work, and credit exposure.", "Financial overview")
    all_businesses = st.toggle("Show combined portfolio", value=False)
    with db.connect(DB_PATH) as connection:
        summary = db.dashboard(connection, None if all_businesses else business_id)
    total_revenue = sum(float(row["revenue"]) for row in summary)
    total_expense = sum(float(row["expense"]) for row in summary)
    total_review = sum(int(row["needs_review"] or 0) for row in summary)
    total_loc = sum(float(row["loc_balance"] or 0) for row in summary)
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Revenue", money(total_revenue), "Confirmed income", "↗", "teal")
    with c2: metric_card("Expenses", money(total_expense), "Net of refunds", "↘", "rose")
    with c3: metric_card("Net position", money(total_revenue - total_expense), "Revenue less expenses", "◆", "navy")
    with c4: metric_card("Needs review", f"{total_review:,}", "Transactions awaiting you", "✓", "gold")
    section_label("Quick actions")
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    with a1:
        st.button(f"✓  Review {total_review:,} waiting", type="primary" if total_review else "secondary",
                  width="stretch", on_click=go_to, args=("✓  Review queue",), disabled=not bool(total_review))
    with a2:
        st.button("↗  Revenue & expense", width="stretch", on_click=go_to, args=("↗  Revenue & expense",))
    with a3:
        st.button("▣  Tax prep", width="stretch", on_click=go_to, args=("▣  Tax prep",))
    with a4:
        st.button("⇧  Import transactions", width="stretch", on_click=go_to, args=("⇧  Import transactions",))
    with a5:
        st.button("≡  Open transaction ledger", width="stretch", on_click=go_to, args=("≡  All transactions",))
    with a6:
        st.button("▤  Reconcile checks", width="stretch", on_click=go_to, args=("▤  Statements & checks",))
    section_label("Business portfolio")
    frame = pd.DataFrame(summary)
    if not frame.empty:
        frame = frame.rename(columns={"business": "Business", "transactions": "Transactions",
                                      "needs_review": "Needs review", "revenue": "Revenue",
                                      "expense": "Expense", "net": "Net", "loc_balance": "LOC balance",
                                      "latest_transaction": "Latest transaction"})
        st.dataframe(frame[["Business", "Transactions", "Needs review", "Revenue", "Expense", "Net", "LOC balance", "Latest transaction"]],
                     hide_index=True, width="stretch",
                     column_config={key: st.column_config.NumberColumn(format="$%.2f") for key in ["Revenue", "Expense", "Net", "LOC balance"]})
    if total_loc:
        st.caption(f"Outstanding line-of-credit principal across this view: {money(total_loc)}")


elif page == "Revenue & Expense":
    page_header("Revenue and expense summary",
                "See confirmed operating activity by month and category. Transfers, loan principal, and excluded items stay outside this view.",
                "Performance statement")
    with db.connect(DB_PATH) as connection:
        pnl_rows = db.list_transactions(connection, business_id, limit=100000)
    pnl = pd.DataFrame(pnl_rows)
    if pnl.empty:
        st.info("No transactions are available yet.")
        st.stop()
    pnl["transaction_date"] = pd.to_datetime(pnl["transaction_date"], errors="coerce")
    valid_dates = pnl["transaction_date"].dropna()
    reporting_year = int(valid_dates.max().year) if not valid_dates.empty else date.today().year
    date_value = (date(reporting_year, 1, 1), date(reporting_year, 12, 31))
    top1, top2 = st.columns([1.2, 2])
    with top1:
        selected_dates = st.date_input("Reporting period", value=date_value)
    with top2:
        selected_categories = st.multiselect(
            "Categories", sorted(pnl["category"].fillna("Uncategorized").unique()),
            placeholder="All categories")
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
        pnl = pnl[(pnl["transaction_date"].dt.date >= start_date) & (pnl["transaction_date"].dt.date <= end_date)]
    pnl["Category"] = pnl["category"].fillna("Uncategorized")
    activity_pnl = pnl.copy()
    if selected_categories:
        pnl = pnl[pnl["Category"].isin(selected_categories)]
    pnl["Revenue"] = pnl.apply(
        lambda row: float(row["signed_amount"]) if row["treatment"] in {"Revenue", "Revenue refund"} else 0.0,
        axis=1)
    pnl["Expense"] = pnl.apply(
        lambda row: abs(float(row["signed_amount"])) if row["treatment"] == "Expense"
        else (-abs(float(row["signed_amount"])) if row["treatment"] == "Expense refund" else 0.0), axis=1)
    operating = pnl[(pnl["Revenue"] != 0) | (pnl["Expense"] != 0)].copy()
    revenue_total = float(operating["Revenue"].sum())
    expense_total = float(operating["Expense"].sum())
    unresolved = int((pnl["status"] == "needs_review").sum())
    m1, m2, m3, m4 = st.columns(4)
    with m1: metric_card("Revenue", money(revenue_total), "After revenue refunds", "↗", "teal")
    with m2: metric_card("Expenses", money(expense_total), "After expense refunds", "↘", "rose")
    with m3: metric_card("Net", money(revenue_total - expense_total), "Operating result", "◆", "navy")
    with m4: metric_card("Unresolved", f"{unresolved:,}", "Not included in totals", "?", "gold")

    section_label("Key business activity summary")
    activity_pnl["_category"] = activity_pnl["Category"].str.lower().str.strip()

    def activity_line(label: str, mask: pd.Series, *, operating_group: bool) -> dict[str, object]:
        rows = activity_pnl[mask]
        if operating_group:
            incoming = float(rows.loc[rows["treatment"].isin(["Revenue", "Revenue refund"]), "signed_amount"].sum())
            expense_rows = rows[rows["treatment"].isin(["Expense", "Expense refund"])]
            outgoing = float(expense_rows.apply(
                lambda row: abs(float(row["signed_amount"])) if row["treatment"] == "Expense"
                else -abs(float(row["signed_amount"])), axis=1).sum()) if not expense_rows.empty else 0.0
            net = incoming - outgoing
        else:
            incoming = float(rows.loc[rows["signed_amount"] > 0, "signed_amount"].sum())
            outgoing = float(rows.loc[rows["signed_amount"] < 0, "signed_amount"].abs().sum())
            net = incoming - outgoing
        return {
            "Activity": label,
            "Incoming / Revenue": incoming,
            "Outgoing / Expense": outgoing,
            "Net / Principal movement": net,
            "Transactions": len(rows),
        }

    category_text = activity_pnl["_category"]
    activity_summary = pd.DataFrame([
        activity_line("Loans",
                      category_text.isin(["loan", "loan repayment"]), operating_group=False),
        activity_line("Internal transfers",
                      category_text.str.contains("internal transfer", regex=False), operating_group=False),
        activity_line("IT staffing",
                      category_text.str.contains("staffing", regex=False), operating_group=True),
        activity_line("IT services",
                      category_text.str.contains("it service", regex=False), operating_group=True),
        activity_line("Prior-year payroll & expenses",
                      category_text.isin(["prior year payroll", "prior year expense"]), operating_group=True),
    ])
    st.dataframe(
        activity_summary, hide_index=True, width="stretch",
        column_config={key: st.column_config.NumberColumn(format="$%.2f") for key in
                       ["Incoming / Revenue", "Outgoing / Expense", "Net / Principal movement"]},
    )
    st.caption("Calendar year runs January 1 through December 31. Loans and internal transfers remain outside profit and loss.")

    if operating.empty:
        st.warning("No categorized revenue or expense transactions match these filters.")
    else:
        operating["Month"] = operating["transaction_date"].dt.to_period("M").astype(str)
        monthly = operating.groupby("Month", as_index=False)[["Revenue", "Expense"]].sum()
        monthly["Net"] = monthly["Revenue"] - monthly["Expense"]
        section_label("Category summary")
        by_category = operating.groupby("Category", as_index=False)[["Revenue", "Expense"]].sum()
        by_category["Net"] = by_category["Revenue"] - by_category["Expense"]
        by_category = by_category.sort_values(["Revenue", "Expense"], ascending=False)
        st.dataframe(by_category, hide_index=True, width="stretch",
                     column_config={key: st.column_config.NumberColumn(format="$%.2f")
                                    for key in ["Revenue", "Expense", "Net"]})
        with st.expander("View monthly totals"):
            st.dataframe(monthly, hide_index=True, width="stretch",
                         column_config={key: st.column_config.NumberColumn(format="$%.2f")
                                        for key in ["Revenue", "Expense", "Net"]})
    section_label("Actions")
    p1, p2 = st.columns(2)
    with p1:
        st.button("≡  Review supporting transactions", width="stretch", on_click=go_to, args=("≡  All transactions",))
    with p2:
        st.button("↓  Export workbook", width="stretch", on_click=go_to, args=("↓  Export & settings",))


elif page == "Tax Prep":
    page_header("Tax preparation workspace",
                "Review the year using your existing classifications. Ledgerly highlights gaps but does not decide tax deductibility.",
                "Year-end readiness")
    with db.connect(DB_PATH) as connection:
        tax_rows = db.list_transactions(connection, business_id, limit=100000)
    tax_frame = pd.DataFrame(tax_rows)
    if tax_frame.empty:
        st.info("No transactions are available yet.")
        st.stop()
    tax_frame["transaction_date"] = pd.to_datetime(tax_frame["transaction_date"], errors="coerce")
    available_years = sorted(tax_frame["transaction_date"].dropna().dt.year.astype(int).unique(), reverse=True)
    tax_year = st.selectbox("Tax year", available_years)
    year_frame = tax_frame[tax_frame["transaction_date"].dt.year == tax_year].copy()
    year_frame["Category"] = year_frame["category"].fillna("Uncategorized")
    year_frame["Revenue"] = year_frame.apply(
        lambda row: float(row["signed_amount"]) if row["treatment"] in {"Revenue", "Revenue refund"} else 0.0,
        axis=1)
    year_frame["Expense"] = year_frame.apply(
        lambda row: abs(float(row["signed_amount"])) if row["treatment"] == "Expense"
        else (-abs(float(row["signed_amount"])) if row["treatment"] == "Expense refund" else 0.0), axis=1)
    tax_revenue = float(year_frame["Revenue"].sum())
    tax_expense = float(year_frame["Expense"].sum())
    review_frame = year_frame[year_frame["status"] == "needs_review"].copy()
    uncategorized_frame = year_frame[
        year_frame["category"].isna() & year_frame["treatment"].isin(["Revenue", "Revenue refund", "Expense", "Expense refund"])
    ].copy()
    excluded_frame = year_frame[year_frame["treatment"].isin(["Transfer", "Loan draw", "Principal repayment", "Loan receivable", "Receivable repayment", "Excluded"])]
    t1, t2, t3, t4 = st.columns(4)
    with t1: metric_card("Gross revenue", money(tax_revenue), f"Tax year {tax_year}", "↗", "teal")
    with t2: metric_card("Recorded expenses", money(tax_expense), "Not a deductibility opinion", "↘", "rose")
    with t3: metric_card("Net before tax", money(tax_revenue - tax_expense), "Revenue less recorded expenses", "◆", "navy")
    with t4: metric_card("Needs review", f"{len(review_frame):,}", "Resolve before handoff", "?", "gold")
    section_label("Readiness checks")
    checks = pd.DataFrame([
        {"Check": "Transactions still needing review", "Count": len(review_frame),
         "Status": "Ready" if review_frame.empty else "Action needed"},
        {"Check": "P&L transactions without a category", "Count": len(uncategorized_frame),
         "Status": "Ready" if uncategorized_frame.empty else "Action needed"},
        {"Check": "Transfers, excluded items, and loan principal", "Count": len(excluded_frame),
         "Status": "Excluded from P&L"},
    ])
    st.dataframe(checks, hide_index=True, width="stretch")
    operating = year_frame[(year_frame["Revenue"] != 0) | (year_frame["Expense"] != 0)]
    left_tax, right_tax = st.columns(2, gap="large")
    with left_tax:
        section_label("Revenue by category")
        revenue_categories = operating.groupby("Category", as_index=False)["Revenue"].sum()
        revenue_categories = revenue_categories[revenue_categories["Revenue"] != 0].sort_values("Revenue", ascending=False)
        st.dataframe(revenue_categories, hide_index=True, width="stretch",
                     column_config={"Revenue": st.column_config.NumberColumn(format="$%.2f")})
    with right_tax:
        section_label("Expenses by category")
        expense_categories = operating.groupby("Category", as_index=False)["Expense"].sum()
        expense_categories = expense_categories[expense_categories["Expense"] != 0].sort_values("Expense", ascending=False)
        st.dataframe(expense_categories, hide_index=True, width="stretch",
                     column_config={"Expense": st.column_config.NumberColumn(format="$%.2f")})
    if not review_frame.empty:
        with st.expander(f"Review {len(review_frame):,} unresolved transactions"):
            st.dataframe(review_frame[["transaction_date", "account", "description", "signed_amount", "status"]],
                         hide_index=True, width="stretch",
                         column_config={"signed_amount": st.column_config.NumberColumn("Amount", format="$%.2f")})
    with db.connect(DB_PATH) as connection:
        tax_workbook = exporter.tax_prep_workbook(connection, business_id, int(tax_year))
    section_label("Tax handoff")
    h1, h2 = st.columns(2)
    with h1:
        st.download_button("Download tax-prep workbook", data=tax_workbook,
                           file_name=f"{db.slugify(business_name)}-{tax_year}-tax-prep.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", width="stretch")
    with h2:
        st.button("✓  Resolve review queue", width="stretch", on_click=go_to, args=("✓  Review queue",),
                  disabled=review_frame.empty)
    st.caption("This view organizes your records for review. Confirm tax treatment and deductibility with your tax professional.")


elif page == "Import / Paste":
    page_header("Bring in new transactions",
                "Upload a statement or paste only the rows you need. Nothing is committed until you approve the preview.",
                "Import center")
    with db.connect(DB_PATH) as connection:
        accounts = [item for item in db.list_accounts(connection, business_id) if item["account_type"] != "line_of_credit"]
    if not accounts:
        st.warning("Add a checking or credit-card account first on Accounts & Credit.")
        st.stop()
    account_by_name = {item["name"]: item for item in accounts}
    selected_account_name = st.selectbox("Account", list(account_by_name))
    selected_account = account_by_name[selected_account_name]
    mode = st.radio("Input", ["Upload CSV", "Paste rows"], horizontal=True)
    text = ""
    source_name = "pasted-rows.csv"
    if mode == "Upload CSV":
        upload = st.file_uploader("Choose a bank CSV", type=["csv"])
        if upload:
            source_name = upload.name
            text = upload.getvalue().decode("utf-8-sig")
    else:
        st.caption("Paste CSV or tab-separated rows. Include Date, Description, Amount.")
        pasted = st.text_area("Rows", height=220, placeholder="Date\tDescription\tAmount\n11/11/2026\tExample\t-25.00")
        text = pasted.replace("\t", ",")

    preview_key = f"preview_{business_id}_{selected_account['id']}"
    if st.button("Preview", disabled=not bool(text.strip()), type="primary"):
        try:
            st.session_state[preview_key] = importers.preview_csv(text, selected_account["account_type"])
            st.session_state[preview_key + "_name"] = source_name
        except Exception as exc:
            st.error(str(exc))
    preview = st.session_state.get(preview_key, [])
    if preview:
        section_label(f"Preview · {len(preview)} rows")
        st.dataframe(pd.DataFrame(preview)[["transaction_date", "description", "source_amount", "signed_amount"]],
                     hide_index=True, width="stretch")
        st.caption("Duplicates are checked again when you import. Learned rules classify matching rows automatically.")
        if st.button("Import these rows", type="primary"):
            with db.connect(DB_PATH) as connection:
                result = importers.commit_rows(connection, business_id=business_id,
                    account_id=int(selected_account["id"]), account_type=selected_account["account_type"],
                    rows=preview, source_name=st.session_state.get(preview_key + "_name", source_name),
                    source_type="paste" if mode == "Paste rows" else "csv")
            st.success(f"Imported {result['imported']}; skipped {result['duplicates']} duplicates; "
                       f"auto-classified {result['auto_classified']}; {result['needs_review']} need review.")
            del st.session_state[preview_key]

    st.divider()
    section_label("Import history")
    with db.connect(DB_PATH) as connection:
        batches = db.list_import_batches(connection, business_id)
    if batches:
        st.dataframe(pd.DataFrame(batches), hide_index=True, width="stretch")
        active = [item for item in batches if not item["undone_at"]]
        if active:
            batch_map = {f"#{item['id']} · {item['source_name']} · {item['imported_count']} rows": item for item in active}
            chosen = st.selectbox("Batch to undo", list(batch_map))
            if st.button("Undo selected import"):
                with db.connect(DB_PATH) as connection:
                    count = db.undo_import_batch(connection, int(batch_map[chosen]["id"]))
                st.success(f"Removed {count} transactions from that batch.")
                rerun()
    else:
        st.info("No imports yet.")


elif page == "Statements & Checks":
    page_header("Statements and checks",
                "Upload one account and month at a time. Preview the statement and check images, then save only the details you confirm.",
                "Reconciliation workspace")
    with db.connect(DB_PATH) as connection:
        accounts = [item for item in db.list_accounts(connection, business_id)
                    if item["account_type"] in {"checking", "savings"}]
        categories = db.list_categories(connection, business_id)
        register = db.list_check_register(connection, business_id)
    if not accounts:
        st.info("Add a checking account under Accounts & Credit before reconciling a statement.")
        st.stop()

    account_by_name = {item["name"]: item for item in accounts}
    category_by_name = {item["name"]: item for item in categories}
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        section_label("1 · Choose files")
        selected_account_name = st.selectbox("Account", list(account_by_name), key="statement_account")
        statement_file = st.file_uploader("Monthly bank statement (PDF)", type=["pdf"], key="statement_pdf")
        if st.button("Analyze statement and checks", type="primary", width="stretch",
                     disabled=statement_file is None):
            try:
                raw_statement = statement_file.getvalue()
                parsed = statements.parse_statement(raw_statement)
                image_sets = (statements.extract_boa_check_image_sets(raw_statement, statement_file.name)
                              if parsed["bank"] == "Bank of America" else [])
                st.session_state["statement_workspace"] = {
                    "account_id": int(account_by_name[selected_account_name]["id"]),
                    "account_name": selected_account_name,
                    "parsed": parsed,
                    "image_sets": image_sets,
                }
                st.success(f"Detected {parsed['bank']}. Found {len(parsed['checks'])} cleared checks and {len(image_sets)} check image set(s).")
            except Exception as exc:
                st.error(str(exc))
    with right:
        section_label("Privacy by design")
        st.markdown(
            '<div class="card"><b>The PDFs are temporary.</b><br><br>'
            'They are read in memory for this reconciliation screen. The database receives only the check details '
            'you confirm, the matched transaction, and the original filename—never the PDF or check image.</div>',
            unsafe_allow_html=True)

    workspace = st.session_state.get("statement_workspace")
    if workspace and int(workspace["account_id"]) == int(account_by_name[selected_account_name]["id"]):
        parsed = workspace["parsed"]
        checks = parsed["checks"]
        register_by_key = {
            (int(item["account_id"]), str(item["check_number"]), item["cleared_date"], round(float(item["amount"]), 2)): item
            for item in register
        }

        def mapped_check(item: dict[str, object]) -> dict[str, object] | None:
            return register_by_key.get((
                int(workspace["account_id"]), str(item["check_number"]),
                str(item["cleared_date"]), round(float(item["amount"]), 2)))

        image_sets = list(workspace["image_sets"])

        section_label("2 · Statement control totals")
        m1, m2, m3, m4 = st.columns(4)
        with m1: metric_card("Bank", parsed["bank"], "Layout detected", "▤", "navy")
        with m2: metric_card("Statement date", parsed["statement_date"], f"Account ending {parsed['account_last4'] or '—'}", "◷", "teal")
        with m3: metric_card("Cleared checks", f"{len(checks):,}", "Listed on statement", "✓", "gold")
        with m4: metric_card("Check total", money(float(parsed["check_total"])), "Statement control total", "$", "rose")
        if checks:
            check_frame = pd.DataFrame(checks).rename(columns={
                "cleared_date": "Cleared date", "check_number": "Check #", "amount": "Amount"})
            check_frame["Status"] = ["Mapped" if mapped_check(item) else "Unmapped" for item in checks]
            st.dataframe(check_frame, hide_index=True, width="stretch",
                         column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        mapped_items = [item for item in checks if mapped_check(item)]
        unmapped_items = [item for item in checks if not mapped_check(item)]
        mapped_total = sum(float(item["amount"]) for item in mapped_items)
        listed_total = sum(float(item["amount"]) for item in checks)
        section_label("Reconciliation progress")
        st.progress(len(mapped_items) / len(checks) if checks else 0.0,
                    text=f"{len(mapped_items)} of {len(checks)} statement checks mapped")
        p1, p2, p3 = st.columns(3)
        with p1: metric_card("Mapped", money(mapped_total), f"{len(mapped_items)} checks in register", "✓", "teal")
        with p2: metric_card("Still to map", money(listed_total - mapped_total), f"{len(unmapped_items)} checks", "◷", "gold")
        with p3: metric_card("Control total", money(float(parsed["check_total"])),
                             "Statement total", "$", "navy")
        if checks and abs(listed_total - float(parsed["check_total"])) >= 0.005:
            st.warning(f"The parsed checks add up to {money(listed_total)} but the statement says "
                       f"{money(float(parsed['check_total']))}. A check may not have been read — compare before relying on this list.")
        elif checks and not unmapped_items:
            st.success("Every check on this statement is in the register and the totals agree.")
        if unmapped_items:
            with st.expander(f"Checks still to map ({len(unmapped_items)})"):
                st.dataframe(pd.DataFrame(unmapped_items).rename(columns={
                    "cleared_date": "Cleared date", "check_number": "Check #", "amount": "Amount"}),
                    hide_index=True, width="stretch",
                    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        selected_account = account_by_name[selected_account_name]
        if parsed["account_last4"] and not selected_account.get("last4"):
            note_col, save_col = st.columns([3, 1])
            note_col.info(f"“{selected_account_name}” has no account number saved, so the account check can't run. "
                          f"This statement is for an account ending {parsed['account_last4']}.")
            if save_col.button(f"Save ending {parsed['account_last4']}", key="save_account_last4"):
                with db.connect(DB_PATH) as connection:
                    db.set_account_last4(connection, int(selected_account["id"]), parsed["account_last4"])
                rerun()
        if selected_account.get("last4") and parsed["account_last4"] and str(selected_account["last4"])[-4:] != parsed["account_last4"]:
            st.warning("The statement account ending does not match the selected account. Choose the correct account before confirming anything.")

        if parsed["bank"] == "Truist":
            section_label("3 · Upload the required Truist check PDFs")
            st.caption("Save each downloaded check PDF using its amount as the filename. You can upload all needed files together.")
            check_files = st.file_uploader(
                "Check PDFs listed below", type=["pdf"], accept_multiple_files=True,
                key=f"truist_check_pdfs_{workspace['account_id']}_{parsed['statement_date']}")
            for uploaded in check_files or []:
                extracted = statements.extract_check_images(uploaded.getvalue())
                if extracted:
                    image_sets.append({"name": uploaded.name, "images": extracted})

            uploaded_indexes = {
                matched for item in image_sets
                if (matched := statements.match_check_index(checks, item["name"])) is not None
            }
            amount_counts: dict[float, int] = {}
            for item in checks:
                amount_key = round(float(item["amount"]), 2)
                amount_counts[amount_key] = amount_counts.get(amount_key, 0) + 1
            needed_rows = []
            for index, item in enumerate(checks):
                amount_value = float(item["amount"])
                amount_text = f"{amount_value:.2f}".rstrip("0").rstrip(".")
                expected_name = (f"{amount_text}.pdf" if amount_counts[round(amount_value, 2)] == 1
                                 else f"{amount_text}-{item['check_number']}.pdf")
                if mapped_check(item):
                    status = "Mapped — no PDF needed"
                elif index in uploaded_indexes:
                    status = "PDF uploaded"
                else:
                    status = "PDF needed"
                needed_rows.append({
                    "Check #": item["check_number"], "Cleared": item["cleared_date"],
                    "Amount": amount_value, "Expected filename": expected_name, "Status": status})
            st.dataframe(pd.DataFrame(needed_rows), hide_index=True, width="stretch",
                         column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})

        stray_files = [item["name"] for item in image_sets
                       if checks and statements.match_check_index(checks, item["name"]) is None]
        if stray_files:
            st.warning("These uploaded files don't match any check on the statement by amount or check number, "
                       "so you'll have to pick the check yourself: " + ", ".join(stray_files))
        section_label(f"{'4' if parsed['bank'] == 'Truist' else '3'} · Identify and confirm each check")
        if not image_sets:
            st.info("The statement is ready. Add downloaded check image PDFs above to identify payees and create register entries.")
        else:
            image_by_name = {item["name"]: item for item in image_sets}
            st.caption("Choose a check, then confirm its details in the panel beside the image.")
            active_image_name = st.selectbox("Check to review", list(image_by_name), key="active_check_image")
            active_image = image_by_name[active_image_name]
            names = list(image_by_name)
            pending_names = [
                name for name in names
                if (idx := statements.match_check_index(checks, name)) is not None and not mapped_check(checks[idx])]
            if pending_names:
                following = [n for n in pending_names if names.index(n) > names.index(active_image_name)]
                target = (following or pending_names)[0]
                if target != active_image_name:
                    st.button(f"Next unmapped check →  {target}", on_click=go_to_check_image, args=(target,))
            elif checks:
                st.caption("No uploaded check image points at an unmapped check.")
            suggested_index = statements.suggest_check_index(checks, active_image_name) if checks else 0
            guessed = bool(checks) and statements.match_check_index(checks, active_image_name) is None
            check_labels = [
                f"#{item['check_number']} · {item['cleared_date']} · {money(float(item['amount']))}"
                f" · {'✓ Mapped' if mapped_check(item) else 'Unmapped'}"
                for item in checks]
            if not check_labels:
                st.warning("No cleared checks were parsed from this statement.")
            else:
                image_column, confirm_column = st.columns([1.15, 1], gap="large")
                with image_column:
                    for index, image_bytes in enumerate(active_image["images"][:2]):
                        st.image(image_bytes, caption="Front" if index == 0 else "Back", width="stretch")
                with confirm_column:
                    st.markdown("#### Confirm this check")
                    if guessed:
                        st.warning(f"“{active_image_name}” doesn't match a check by amount or number. "
                                   "The first check is selected only as a placeholder — choose the right one below.")
                    chosen_label = st.selectbox("Statement check", check_labels, index=suggested_index,
                                                key=f"statement_check_{active_image_name}")
                    chosen = checks[check_labels.index(chosen_label)]
                    existing = mapped_check(chosen)
                    if existing:
                        st.success("Already mapped. Saving below updates the existing register entry; it does not create a duplicate.")
                    check_type_key = f"check_type_{active_image_name}_{chosen['check_number']}"
                    saved_check_type = str(existing.get("check_type") or "payment") if existing else "payment"
                    if check_type_key not in st.session_state:
                        st.session_state[check_type_key] = saved_check_type
                    check_type = st.radio(
                        "Check direction",
                        list(db.CHECK_TYPES),
                        key=check_type_key,
                        format_func=lambda value: (
                            "Payment / money paid" if value == "payment" else "Deposit / money received"
                        ),
                        horizontal=True,
                        help="Payment matches money leaving the account. Deposit matches money entering the account.",
                    )
                    with db.connect(DB_PATH) as connection:
                        candidates = db.find_check_transaction_candidates(
                            connection, business_id=business_id, account_id=int(workspace["account_id"]),
                            amount=float(chosen["amount"]), cleared_date=chosen["cleared_date"],
                            check_type=check_type, check_number=str(chosen["check_number"]))
                    candidate_labels = ["No transaction match — register only"] + [
                        f"{'★ check # match · ' if item.get('number_match') else ''}"
                        f"#{item['id']} · {item['transaction_date']} · {money(float(item['signed_amount']))} · {item['description'][:80]}"
                        for item in candidates]
                    category_options = ["Uncategorized"] + list(category_by_name)
                    category_defaults = {"Uncategorized": "Needs review", **{
                        name: item["default_treatment"] for name, item in category_by_name.items()}}
                    saved_category = str(existing.get("category") or "Uncategorized") if existing else "Uncategorized"
                    category_key = f"check_category_{active_image_name}_{chosen['check_number']}"
                    treatment_key = f"check_treatment_{active_image_name}_{chosen['check_number']}"
                    if category_key not in st.session_state:
                        st.session_state[category_key] = saved_category if saved_category in category_options else "Uncategorized"
                    if treatment_key not in st.session_state:
                        st.session_state[treatment_key] = (
                            str(existing.get("treatment") or "Needs review") if existing
                            else ("Revenue" if check_type == "deposit" else "Expense")
                            if st.session_state[category_key] == "Uncategorized"
                            else category_defaults[st.session_state[category_key]])
                    st.session_state.setdefault(f"check_direction_previous_{active_image_name}_{chosen['check_number']}", check_type)
                    previous_direction_key = f"check_direction_previous_{active_image_name}_{chosen['check_number']}"
                    if st.session_state[previous_direction_key] != check_type:
                        sync_check_direction(check_type_key, category_key, treatment_key)
                        st.session_state[previous_direction_key] = check_type
                    category_name = st.selectbox(
                        "Category", category_options, key=category_key,
                        on_change=sync_category_treatment,
                        args=(category_key, treatment_key, category_defaults),
                        help="Selecting Loan automatically chooses Loan draw; Loan repayment chooses Principal repayment. For money you lend out, pick the Loan receivable treatment; when it is repaid, Receivable repayment.")
                    treatment_options = list(db.TREATMENTS)
                    treatment = st.selectbox("Treatment", treatment_options, key=treatment_key)
                    counterparty_label = {
                        "Loan draw": "Loan received from",
                        "Principal repayment": "Loan repaid to",
            "Loan receivable": "Loan made to",
            "Receivable repayment": "Loan repaid by",
                        "Revenue": "Received from / customer",
                        "Revenue refund": "Refund paid to",
                        "Expense": "Paid to / payee",
                        "Expense refund": "Refund received from",
                        "Transfer": "Transferred to / from",
                    }.get(treatment, "Counterparty — paid to or received from")
                    payee_key = f"check_payee_{active_image_name}_{chosen['check_number']}"
                    memo_key = f"check_memo_{active_image_name}_{chosen['check_number']}"
                    history_key = f"check_history_{active_image_name}_{chosen['check_number']}"
                    with db.connect(DB_PATH) as connection:
                        history_items = db.payee_history(connection, business_id)
                    history_map = {f"{item['payee']} · last {item['treatment'] or '—'}": item for item in history_items}
                    st.session_state["_check_category_names"] = tuple(category_by_name)
                    if payee_key not in st.session_state:
                        st.session_state[payee_key] = str(existing.get("payee") or "") if existing else ""
                    if memo_key not in st.session_state:
                        st.session_state[memo_key] = str(existing.get("memo") or "") if existing else ""
                    if history_map:
                        st.selectbox(
                            "Use a counterparty you've entered before", [""] + list(history_map), key=history_key,
                            format_func=lambda value: value or "— type a new one below —",
                            on_change=apply_payee_history,
                            args=(history_key, payee_key, memo_key, category_key, treatment_key, history_map),
                            help="Fills in the name, memo, category and treatment from the last check to this counterparty.")
                    with st.form(f"confirm_check_{active_image_name}_{chosen['check_number']}"):
                        candidate_index = next(
                            (index + 1 for index, item in enumerate(candidates)
                             if existing and int(item["id"]) == int(existing.get("transaction_id") or 0)), 0)
                        if not existing or not existing.get("transaction_id"):
                            candidate_index = next(
                                (index + 1 for index, item in enumerate(candidates) if item.get("number_match")),
                                candidate_index)
                        transaction_label = st.selectbox("Existing transaction match", candidate_labels, index=candidate_index)
                        payee = st.text_input(counterparty_label, key=payee_key,
                                              placeholder="Read from the check image")
                        memo = st.text_input("Memo / purpose", key=memo_key, placeholder="Optional")
                        saved_written_date = (existing.get("written_date") if existing else None) or chosen["cleared_date"]
                        written_date = st.date_input("Date written", value=pd.to_datetime(saved_written_date).date())
                        confirmed = st.form_submit_button(
                            "Update mapped check" if existing else "Confirm and add to check register",
                            type="primary", width="stretch")
                        if confirmed:
                            candidate_index = candidate_labels.index(transaction_label) - 1
                            transaction_id = int(candidates[candidate_index]["id"]) if candidate_index >= 0 else None
                            category_id = (int(category_by_name[category_name]["id"])
                                           if category_name in category_by_name else None)
                            with db.connect(DB_PATH) as connection:
                                spelled = db.canonical_payee(connection, business_id, payee)
                                if spelled and spelled != payee.strip():
                                    st.info(f"Saved as “{spelled}”, matching an existing counterparty.")
                                    payee = spelled
                                db.confirm_check(
                                    connection, business_id=business_id, account_id=int(workspace["account_id"]),
                                    transaction_id=transaction_id, bank_name=parsed["bank"],
                                    account_last4=parsed["account_last4"], statement_date=parsed["statement_date"],
                                    check_number=str(chosen["check_number"]), amount=float(chosen["amount"]),
                                    written_date=written_date.isoformat(), cleared_date=chosen["cleared_date"],
                                    payee=payee, memo=memo, category_id=category_id, treatment=treatment,
                                    source_file_name=active_image_name, check_type=check_type)
                            st.success(f"Check #{chosen['check_number']} was saved in the register.")
                            rerun()
        if st.button("Clear temporary PDF previews"):
            st.session_state.pop("statement_workspace", None)
            rerun()

    section_label("Confirmed check register")
    with db.connect(DB_PATH) as connection:
        register = db.list_check_register(connection, business_id)
    if register:
        register_frame = pd.DataFrame(register).rename(columns={
            "cleared_date": "Cleared", "written_date": "Written", "check_number": "Check #",
            "amount": "Amount", "payee": "Counterparty", "memo": "Memo", "bank_name": "Bank",
            "account": "Account", "category": "Category", "treatment": "Treatment",
            "check_type": "Direction",
            "transaction_id": "Transaction #", "source_file_name": "Source file"})
        register_frame["Direction"] = register_frame["Direction"].map({
            "payment": "Payment / money paid", "deposit": "Deposit / money received"}).fillna(register_frame["Direction"])
        @st.dialog("Delete check register entry?")
        def confirm_delete_dialog(selected_check: dict) -> None:
            st.write(
                f"Remove **check #{selected_check['check_number']}** · {selected_check['cleared_date']} · "
                f"{money(float(selected_check['amount']))} · {selected_check.get('payee') or 'No counterparty'}?")
            linked = selected_check.get("transaction_id")
            reset_linked = False
            if linked:
                reset_linked = st.checkbox(
                    f"Also send bank transaction #{linked} back to the Review Queue", value=True,
                    help="Clears its category and treatment. The transaction itself is never deleted.")
            else:
                st.caption("This check has no linked bank transaction.")
            st.caption("The bank transaction is never deleted.")
            yes, no = st.columns(2)
            if yes.button("Delete", type="primary", width="stretch"):
                with db.connect(DB_PATH) as connection:
                    db.delete_check_register_entry(
                        connection, business_id=business_id, check_id=int(selected_check["id"]),
                        reset_transaction=reset_linked)
                st.session_state.pop("check_register_grid", None)
                rerun()
            if no.button("Cancel", width="stretch"):
                st.rerun()

        st.caption("Select a row in the grid to delete it.")
        grid = st.dataframe(
            register_frame[["Cleared", "Written", "Check #", "Direction", "Amount", "Counterparty", "Memo", "Bank",
                            "Account", "Category", "Treatment", "Transaction #", "Source file"]],
            hide_index=True, width="stretch", key="check_register_grid",
            on_select="rerun", selection_mode="single-row",
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        selected_rows = grid.selection.rows
        if st.button("🗑  Delete selected check", disabled=not selected_rows, key="delete_check_register_button"):
            confirm_delete_dialog(register[selected_rows[0]])
    else:
        st.caption("No checks have been confirmed yet.")


elif page == "Review Queue":
    page_header("Turn uncertainty into clean books",
                "Make one decision and Ledgerly remembers it for similar transactions in this account.",
                "Review queue")
    with db.connect(DB_PATH) as connection:
        queue = db.list_transactions(connection, business_id, status="needs_review", limit=5000)
        categories = db.list_categories(connection, business_id)
        accounts = db.list_accounts(connection, business_id)
    st.caption(f"{len(queue):,} transactions remain · each saved decision also teaches a local rule")
    if not queue:
        st.success("Nothing needs review.")
        st.stop()
    item_by_label = {f"{row['transaction_date']} · {money(row['signed_amount'])} · {row['description'][:75]}": row for row in queue}
    label = st.selectbox("Transaction", list(item_by_label))
    row = item_by_label[label]
    category_by_name = {item["name"]: item for item in categories}
    category_defaults = {item["name"]: item["default_treatment"] for item in categories}
    left, right = st.columns([.9, 1.1], gap="large")
    with left:
        amount_color = "#6ee7d8" if float(row["signed_amount"]) >= 0 else "#ffadba"
        st.markdown(
            f'<div class="transaction-card"><div class="meta">{escape(str(row["transaction_date"]))} · Transaction to review</div>'
            f'<div class="desc">{escape(str(row["description"]))}</div>'
            f'<div class="amount" style="color:{amount_color}">{escape(money(row["signed_amount"]))}</div>'
            f'<div class="account">{escape(str(row["account"]))}</div></div>', unsafe_allow_html=True)
        st.caption(f"Bank category: {row.get('source_category') or 'Not supplied'}")
        st.caption("Use short matching text such as MULTIVISIONOPERA. Vendor mappings apply across this business.")
    with right:
        category_key = f"review_category_{row['id']}"
        treatment_key = f"review_treatment_{row['id']}"
        if treatment_key not in st.session_state:
            st.session_state[treatment_key] = "Revenue" if float(row["signed_amount"]) >= 0 else "Expense"
        category_name = st.selectbox(
            "Category", ["— No category —"] + list(category_by_name), key=category_key,
            on_change=sync_category_treatment, args=(category_key, treatment_key, category_defaults),
            help="Selecting a category automatically selects its default revenue or expense treatment.")
        treatment = st.selectbox("Accounting treatment", list(db.TREATMENTS[:-1]), key=treatment_key)
        related_options = {"— None —": None, **{item["name"]: int(item["id"]) for item in accounts}}
        related_name = st.selectbox("Related account", list(related_options), key=f"review_related_{row['id']}",
                                     help="Use for transfers, loan draws, principal repayments, and loans receivable.")
        suggested_pattern = db.suggested_vendor_pattern(row["description"])
        pattern = st.text_input("Description contains (partial match)", value=suggested_pattern,
                                key=f"review_pattern_{row['id']}",
                                help="Use the shortest stable vendor text, for example MULTIVISIONOPERA.")
        counterparty_label = {
            "Loan draw": "Loan received from",
            "Principal repayment": "Loan repaid to",
            "Loan receivable": "Loan made to",
            "Receivable repayment": "Loan repaid by",
            "Revenue": "Received from / customer",
            "Revenue refund": "Refund paid to",
            "Expense": "Paid to / vendor",
            "Expense refund": "Refund received from",
            "Transfer": "Transferred to / from",
        }.get(treatment, "Counterparty name")
        vendor_name = st.text_input(counterparty_label, value=suggested_pattern,
                                    key=f"review_vendor_{row['id']}")
        save_vendor = st.checkbox("Save this counterparty mapping", value=True,
                                  key=f"review_save_vendor_{row['id']}",
                                  help="Future matching transactions will receive this category and treatment automatically.")
        apply_existing = st.checkbox("Apply to matching transactions already waiting", value=True,
                                     key=f"review_apply_{row['id']}")
        notes = st.text_input("Optional note", key=f"review_notes_{row['id']}")
        if st.button("Save decision & learn", type="primary", width="stretch", key=f"review_save_{row['id']}"):
            category_id = int(category_by_name[category_name]["id"]) if category_name in category_by_name else None
            if save_vendor and category_id is None:
                st.error("Select a category before saving a vendor mapping.")
            elif len(db.normalize_description(pattern)) < 3:
                st.error("Use at least three characters for the partial match.")
            else:
                with db.connect(DB_PATH) as connection:
                    if save_vendor:
                        _, applied = db.upsert_vendor(
                            connection, business_id=business_id, name=vendor_name,
                            match_pattern=pattern, category_id=category_id, treatment=treatment,
                            apply_existing=apply_existing)
                        db.update_transaction_classification(
                            connection, int(row["id"]), category_id=category_id, treatment=treatment,
                            related_account_id=related_options[related_name], notes=notes)
                    else:
                        _, applied = db.classify_transaction(
                            connection, int(row["id"]), category_id=category_id,
                            treatment=treatment, related_account_id=related_options[related_name], notes=notes,
                            pattern=pattern, apply_existing=apply_existing)
                st.success(f"Saved. {max(applied - (1 if save_vendor else 0), 0)} other matching waiting transaction(s) were classified.")
                rerun()


elif page == "Transactions":
    page_header("Every transaction, one ledger",
                "Search every visible field and combine date, account, category, treatment, and status filters.",
                "Transaction ledger")
    with db.connect(DB_PATH) as connection:
        accounts = db.list_accounts(connection, business_id)
        categories = db.list_categories(connection, business_id)
        rows = db.list_transactions(connection, business_id, limit=100000)
    search = st.text_input("Search all transaction fields", placeholder="Merchant, amount, note, reference, category…")
    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No transactions are available yet.")
        st.stop()
    frame["transaction_date"] = pd.to_datetime(frame["transaction_date"], errors="coerce")
    frame["category"] = frame["category"].fillna("Uncategorized")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        account_filters = st.multiselect("Accounts", sorted(frame["account"].dropna().unique()),
                                         placeholder="All accounts")
    with f2:
        category_filters = st.multiselect("Categories", sorted(frame["category"].unique()),
                                          placeholder="All categories")
    with f3:
        treatment_filters = st.multiselect("Treatments", sorted(frame["treatment"].dropna().unique()),
                                           placeholder="All treatments")
    with f4:
        status_filters = st.multiselect("Statuses", sorted(frame["status"].dropna().unique()),
                                        placeholder="All statuses")
    valid_dates = frame["transaction_date"].dropna()
    date_value = (valid_dates.min().date(), valid_dates.max().date()) if not valid_dates.empty else (date.today(), date.today())
    selected_dates = st.date_input("Transaction date range", value=date_value)
    filtered = frame.copy()
    if search.strip():
        searchable = filtered.fillna("").astype(str).agg(" | ".join, axis=1)
        filtered = filtered[searchable.str.contains(re.escape(search.strip()), case=False, na=False)]
    if account_filters:
        filtered = filtered[filtered["account"].isin(account_filters)]
    if category_filters:
        filtered = filtered[filtered["category"].isin(category_filters)]
    if treatment_filters:
        filtered = filtered[filtered["treatment"].isin(treatment_filters)]
    if status_filters:
        filtered = filtered[filtered["status"].isin(status_filters)]
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
        filtered = filtered[(filtered["transaction_date"].dt.date >= start_date) &
                            (filtered["transaction_date"].dt.date <= end_date)]
    sort1, sort2 = st.columns([2, 1])
    sortable_columns = {
        "Date": "transaction_date", "Account": "account", "Description": "description",
        "Amount": "signed_amount", "Category": "category", "Treatment": "treatment",
        "Status": "status", "Reference": "source_reference", "Notes": "notes",
    }
    with sort1:
        sort_label = st.selectbox("Sort by", list(sortable_columns))
    with sort2:
        sort_direction = st.radio("Direction", ["Newest / Z–A", "Oldest / A–Z"], horizontal=True)
    filtered = filtered.sort_values(sortable_columns[sort_label],
                                    ascending=sort_direction == "Oldest / A–Z", na_position="last")
    filtered["transaction_date"] = filtered["transaction_date"].dt.strftime("%Y-%m-%d")
    r1, r2 = st.columns([3, 1])
    with r1:
        st.caption(f"Showing {len(filtered):,} of {len(frame):,} transactions")
    with r2:
        st.download_button("Download filtered CSV", filtered.to_csv(index=False).encode("utf-8"),
                           file_name=f"{db.slugify(business_name)}-filtered-transactions.csv",
                           mime="text/csv", width="stretch")
    section_label("Editable transaction grid")
    st.caption("Check rows for bulk changes. Edit Category or Treatment directly; copy/paste and drag-fill work like a spreadsheet.")
    category_names = [item["name"] for item in categories]
    category_by_name = {item["name"]: item for item in categories}
    select_all_visible = st.checkbox("Check all filtered transactions", value=False,
                                     help="Selects every transaction matching the current search and filters.")
    editor_columns = ["id", "transaction_date", "account", "description", "signed_amount", "category",
                      "treatment", "status", "source_reference", "notes"]
    editor_source = filtered[editor_columns].copy()
    editor_source.insert(0, "Select", select_all_visible)
    editor_source = editor_source.set_index("id", drop=False)
    editor_key = (f"transaction_editor_{business_id}_{len(editor_source)}_"
                  f"{int(editor_source['id'].sum()) if len(editor_source) else 0}_{int(select_all_visible)}")
    edited = st.data_editor(
        editor_source,
        hide_index=True,
        width="stretch",
        height=650,
        key=editor_key,
        disabled=["id", "transaction_date", "account", "description", "signed_amount",
                  "status", "source_reference", "notes"],
        column_order=["Select", "transaction_date", "account", "description", "signed_amount",
                      "category", "treatment", "status", "source_reference", "notes"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", help="Select rows for a bulk category change"),
            "transaction_date": st.column_config.TextColumn("Date"),
            "signed_amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
            "category": st.column_config.SelectboxColumn("Category", options=["Uncategorized"] + category_names,
                                                           required=True),
            "treatment": st.column_config.SelectboxColumn("Treatment", options=list(db.TREATMENTS[:-1]),
                                                            required=True),
        },
    )
    changed_ids = []
    for transaction_id, edited_row in edited.iterrows():
        original_row = editor_source.loc[transaction_id]
        if (edited_row["category"] != original_row["category"] or
                edited_row["treatment"] != original_row["treatment"]):
            changed_ids.append(int(transaction_id))
    selected_ids = [int(transaction_id) for transaction_id, row in edited.iterrows() if bool(row["Select"])]
    save1, save2 = st.columns([1, 2])
    with save1:
        if st.button(f"Save {len(changed_ids):,} edited row(s)", type="primary", width="stretch",
                     disabled=not changed_ids):
            saved = 0
            with db.connect(DB_PATH) as connection:
                for transaction_id in changed_ids:
                    row = edited.loc[transaction_id]
                    category_name = str(row["category"] or "Uncategorized")
                    category_id = None if category_name == "Uncategorized" else int(category_by_name[category_name]["id"])
                    if category_id is None:
                        db.update_transaction_classification(connection, transaction_id,
                                                             category_id=None, treatment=str(row["treatment"]))
                    else:
                        db.classify_transaction(connection, transaction_id, category_id=category_id,
                                                treatment=str(row["treatment"]), apply_existing=False)
                    saved += 1
            st.success(f"Saved {saved} row(s). Category choices were learned as local rules.")
            rerun()
    with save2:
        st.caption(f"{len(selected_ids):,} row(s) selected for bulk actions · {len(changed_ids):,} unsaved cell edit(s)")
    section_label("Bulk category action")
    bulk1, bulk2, bulk3 = st.columns([2, 2, 1])
    with bulk1:
        bulk_category = st.selectbox("Set category", ["— Choose category —", "— Clear category —"] + category_names)
    with bulk2:
        bulk_treatment = st.selectbox("Treatment", ["Use category default"] + list(db.TREATMENTS[:-1]))
    with bulk3:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if st.button("Apply to selected", width="stretch", disabled=not selected_ids or bulk_category == "— Choose category —"):
            with db.connect(DB_PATH) as connection:
                for transaction_id in selected_ids:
                    if bulk_category == "— Clear category —":
                        db.update_transaction_classification(connection, transaction_id, category_id=None)
                    else:
                        chosen_category = category_by_name[bulk_category]
                        chosen_treatment = (chosen_category["default_treatment"] if bulk_treatment == "Use category default"
                                            else bulk_treatment)
                        db.classify_transaction(connection, transaction_id,
                                                category_id=int(chosen_category["id"]),
                                                treatment=chosen_treatment, apply_existing=False)
            action = "cleared categories from" if bulk_category == "— Clear category —" else f"set {bulk_category} on"
            st.success(f"Successfully {action} {len(selected_ids)} transaction(s).")
            rerun()
    with st.expander("＋ Add a transaction category"):
        with st.form("transaction_add_category", clear_on_submit=True):
            new_category_name = st.text_input("Category name")
            new_category_treatment = st.selectbox("Default treatment", list(db.TREATMENTS[:-1]))
            if st.form_submit_button("Add category", type="primary") and new_category_name.strip():
                with db.connect(DB_PATH) as connection:
                    db.get_or_create_category(connection, business_id, new_category_name.strip(), new_category_treatment)
                st.success(f"Added {new_category_name.strip()}.")
                rerun()


elif page == "Vendors":
    page_header("Vendor and customer mappings",
                "Store a short matching phrase once, then automatically apply its category and accounting treatment during future imports.",
                "Mapping directory")
    with db.connect(DB_PATH) as connection:
        categories = db.list_categories(connection, business_id)
        vendors = db.list_vendors(connection, business_id, include_inactive=True)
    if not categories:
        st.warning("Create at least one category before adding a vendor mapping.")
        st.stop()
    category_by_name = {item["name"]: item for item in categories}
    category_defaults = {item["name"]: item["default_treatment"] for item in categories}
    left, right = st.columns(2, gap="large")
    with left:
        section_label("Add a mapping")
        new_vendor_name = st.text_input("Vendor / customer name", key="new_vendor_name")
        new_vendor_pattern = st.text_input("Description contains", key="new_vendor_pattern",
                                           placeholder="MULTIVISIONOPERA")
        new_vendor_category_key = "new_vendor_category"
        new_vendor_treatment_key = "new_vendor_treatment"
        if new_vendor_treatment_key not in st.session_state:
            st.session_state[new_vendor_treatment_key] = categories[0]["default_treatment"]
        new_vendor_category = st.selectbox(
            "Category", list(category_by_name), key=new_vendor_category_key,
            on_change=sync_category_treatment,
            args=(new_vendor_category_key, new_vendor_treatment_key, category_defaults))
        new_vendor_treatment = st.selectbox("Treatment", list(db.TREATMENTS[:-1]), key=new_vendor_treatment_key)
        new_vendor_apply = st.checkbox("Classify matching transactions already waiting", value=True,
                                       key="new_vendor_apply")
        if st.button("Add vendor mapping", type="primary", width="stretch"):
            try:
                with db.connect(DB_PATH) as connection:
                    _, applied = db.upsert_vendor(
                        connection, business_id=business_id, name=new_vendor_name,
                        match_pattern=new_vendor_pattern,
                        category_id=int(category_by_name[new_vendor_category]["id"]),
                        treatment=new_vendor_treatment, apply_existing=new_vendor_apply)
                st.success(f"Vendor saved. {applied} waiting transaction(s) were classified.")
                rerun()
            except Exception as exc:
                st.error(str(exc))
    with right:
        section_label("Manage a mapping")
        if not vendors:
            st.info("No vendor mappings yet. Save one during Review or add it here.")
        else:
            vendor_by_label = {
                f"{item['name']} · contains {item['match_pattern']}{' · inactive' if not item['active'] else ''}": item
                for item in vendors
            }
            vendor_label = st.selectbox("Vendor mapping", list(vendor_by_label))
            vendor = vendor_by_label[vendor_label]
            with st.form("manage_vendor"):
                edit_vendor_name = st.text_input("Name", value=vendor["name"])
                edit_vendor_pattern = st.text_input("Description contains", value=vendor["match_pattern"])
                edit_category_names = list(category_by_name)
                edit_category_index = edit_category_names.index(vendor["category_name"]) if vendor["category_name"] in edit_category_names else 0
                edit_vendor_category = st.selectbox("Category", edit_category_names, index=edit_category_index)
                treatment_options = list(db.TREATMENTS[:-1])
                edit_treatment_index = treatment_options.index(vendor["treatment"]) if vendor["treatment"] in treatment_options else 0
                edit_vendor_treatment = st.selectbox("Treatment", treatment_options, index=edit_treatment_index)
                edit_vendor_active = st.checkbox("Active", value=bool(vendor["active"]))
                edit_vendor_apply = st.checkbox("Apply updated mapping to waiting transactions", value=True)
                if st.form_submit_button("Save vendor changes", width="stretch"):
                    try:
                        with db.connect(DB_PATH) as connection:
                            _, applied = db.upsert_vendor(
                                connection, business_id=business_id, vendor_id=int(vendor["id"]),
                                name=edit_vendor_name, match_pattern=edit_vendor_pattern,
                                category_id=int(category_by_name[edit_vendor_category]["id"]),
                                treatment=edit_vendor_treatment, active=edit_vendor_active,
                                apply_existing=edit_vendor_apply)
                        st.success(f"Vendor updated. {applied} waiting transaction(s) were classified.")
                        rerun()
                    except Exception as exc:
                        st.error(str(exc))
    section_label("Vendor table")
    if vendors:
        vendor_frame = pd.DataFrame(vendors).rename(columns={
            "name": "Vendor / customer", "match_pattern": "Description contains",
            "category_name": "Category", "treatment": "Treatment", "hit_count": "Rule matches",
            "active": "Active"})
        st.dataframe(vendor_frame[["Vendor / customer", "Description contains", "Category", "Treatment", "Rule matches", "Active"]],
                     hide_index=True, width="stretch")


elif page == "Categories & Rules":
    page_header("Your accounting vocabulary",
                "Categories organize reporting. Learned rules quietly handle repeat descriptions and remain fully editable.",
                "Automation library")
    left, right = st.columns([1, 2])
    with left:
        section_label("Add a category")
        with st.form("add_category"):
            category_name = st.text_input("Category name")
            default_treatment = st.selectbox("Default treatment", list(db.TREATMENTS[:-1]))
            if st.form_submit_button("Add category", type="primary") and category_name.strip():
                with db.connect(DB_PATH) as connection:
                    db.get_or_create_category(connection, business_id, category_name.strip(), default_treatment)
                rerun()
        section_label("Manage a category")
        with db.connect(DB_PATH) as connection:
            managed_categories = db.list_categories(connection, business_id, include_inactive=True)
        if managed_categories:
            managed_by_label = {
                f"{item['name']}{' · inactive' if not item['active'] else ''}": item
                for item in managed_categories
            }
            managed_label = st.selectbox("Category to manage", list(managed_by_label))
            managed = managed_by_label[managed_label]
            with st.form("manage_category"):
                managed_name = st.text_input("Name", value=managed["name"])
                treatment_options = list(db.TREATMENTS[:-1])
                treatment_index = treatment_options.index(managed["default_treatment"]) if managed["default_treatment"] in treatment_options else 0
                managed_treatment = st.selectbox("Default treatment", treatment_options, index=treatment_index)
                managed_active = st.checkbox("Active", value=bool(managed["active"]),
                                             help="Inactive categories remain on old transactions but are hidden from new selections.")
                if st.form_submit_button("Save category changes", width="stretch"):
                    try:
                        with db.connect(DB_PATH) as connection:
                            db.update_category(connection, int(managed["id"]), name=managed_name,
                                               default_treatment=managed_treatment, active=managed_active)
                        st.success("Category updated.")
                        rerun()
                    except Exception as exc:
                        st.error(str(exc))
        with db.connect(DB_PATH) as connection:
            category_rows = db.category_summary(connection, business_id)
        st.dataframe(pd.DataFrame(category_rows), hide_index=True, width="stretch")
    with right:
        section_label("What Ledgerly has learned")
        with db.connect(DB_PATH) as connection:
            rules = db.list_rules(connection, business_id)
        if rules:
            st.dataframe(pd.DataFrame(rules)[["id", "pattern", "account_name", "category_name", "treatment", "hit_count", "active"]],
                         hide_index=True, width="stretch")
            rule_ids = {f"#{item['id']} · {item['pattern'][:70]}": item for item in rules}
            chosen = st.selectbox("Rule", list(rule_ids))
            active = bool(rule_ids[chosen]["active"])
            if st.button("Disable rule" if active else "Enable rule"):
                with db.connect(DB_PATH) as connection:
                    db.set_rule_active(connection, int(rule_ids[chosen]["id"]), not active)
                rerun()
        else:
            st.info("Rules appear here after you categorize transactions.")


elif page == "Manage Business":
    page_header("Manage businesses",
                "Create or rename a business without disturbing its accounts, transactions, categories, or learned rules.",
                "Business administration")
    with db.connect(DB_PATH) as connection:
        business_overview = db.dashboard(connection)
        current_accounts = db.list_accounts(connection, business_id)
        current_categories = db.list_categories(connection, business_id, include_inactive=True)
    b1, b2, b3, b4 = st.columns(4)
    current_summary = next(item for item in business_overview if int(item["business_id"]) == business_id)
    with b1: metric_card("Transactions", f"{int(current_summary['transactions']):,}", "All imported rows", "≡", "navy")
    with b2: metric_card("Needs review", f"{int(current_summary['needs_review'] or 0):,}", "Still awaiting a decision", "?", "gold")
    with b3: metric_card("Accounts", f"{len(current_accounts):,}", "Bank, card, and credit", "◇", "teal")
    with b4: metric_card("Categories", f"{len(current_categories):,}", "Active and inactive", "⌁", "rose")
    section_label("Default business")
    default_name = next((name for name in business_names
                         if str(business_by_name[name]["id"]) == default_business_id), business_names[0])
    default_choice = st.selectbox("Open this business by default", business_names,
                                  index=business_names.index(default_name))
    if st.button("Save default business"):
        with db.connect(DB_PATH) as connection:
            db.set_setting(connection, "default_business_id", str(business_by_name[default_choice]["id"]))
        st.success(f"{default_choice} will open by default in new sessions.")
    left, right = st.columns(2, gap="large")
    with left:
        section_label("Rename current business")
        with st.form("rename_business"):
            renamed_business = st.text_input("Business name", value=business_name)
            if st.form_submit_button("Save business name", type="primary", width="stretch"):
                try:
                    with db.connect(DB_PATH) as connection:
                        db.update_business(connection, business_id, renamed_business)
                    st.success("Business name updated.")
                    rerun()
                except Exception as exc:
                    st.error(str(exc))
    with right:
        section_label("Create another business")
        with st.form("manage_create_business", clear_on_submit=True):
            managed_new_business = st.text_input("New business name")
            if st.form_submit_button("Create business", width="stretch") and managed_new_business.strip():
                try:
                    with db.connect(DB_PATH) as connection:
                        db.get_or_create_business(connection, managed_new_business.strip())
                    st.success("Business created. Select it from the sidebar to add accounts and transactions.")
                    rerun()
                except Exception as exc:
                    st.error(str(exc))
    section_label("All businesses")
    overview_frame = pd.DataFrame(business_overview).rename(columns={
        "business": "Business", "transactions": "Transactions", "needs_review": "Needs review",
        "revenue": "Revenue", "expense": "Expense", "net": "Net",
        "loc_balance": "LOC balance", "latest_transaction": "Latest transaction"})
    st.dataframe(overview_frame[["Business", "Transactions", "Needs review", "Revenue", "Expense", "Net", "LOC balance", "Latest transaction"]],
                 hide_index=True, width="stretch",
                 column_config={key: st.column_config.NumberColumn(format="$%.2f")
                                for key in ["Revenue", "Expense", "Net", "LOC balance"]})
    st.info("Businesses are not deleted from this screen so historical accounting records cannot be removed accidentally.")


elif page == "Accounts & Credit":
    page_header("Accounts and credit",
                "Keep operating accounts and borrowing in one view without mixing principal movements into revenue or expense.",
                "Account center")
    with db.connect(DB_PATH) as connection:
        accounts = db.account_summaries(connection, business_id)
    st.dataframe(pd.DataFrame(accounts), hide_index=True, width="stretch")
    with db.connect(DB_PATH) as connection:
        receivables = db.list_loan_receivables(connection, business_id)
    if receivables:
        section_label("Loans receivable — money owed to you")
        receivable_frame = pd.DataFrame(receivables).rename(columns={
            "counterparty": "Borrower", "lent": "Lent", "repaid": "Repaid", "balance_owed": "Balance owed"})
        st.dataframe(receivable_frame, hide_index=True, width="stretch", column_config={
            col: st.column_config.NumberColumn(format="$%.2f") for col in ("Lent", "Repaid", "Balance owed")})
        st.caption("Built from check-register entries and bank transactions with the Loan receivable and "
                   "Receivable repayment treatments. Neither affects profit and loss.")
    left, right = st.columns(2)
    with left:
        section_label("Add an account")
        with st.form("add_account"):
            account_name = st.text_input("Account name")
            account_type = st.selectbox("Type", list(db.ACCOUNT_TYPES))
            institution = st.text_input("Institution")
            last4 = st.text_input("Last 4 digits")
            opening = st.number_input("Opening balance", value=0.0, step=100.0)
            limit = st.number_input("Credit limit", value=0.0, step=100.0)
            if st.form_submit_button("Add account", type="primary") and account_name.strip():
                with db.connect(DB_PATH) as connection:
                    db.get_or_create_account(connection, business_id, account_name.strip(), account_type,
                                             institution, last4, opening, limit)
                rerun()
    with right:
        section_label("Record credit activity")
        locs = [item for item in accounts if item["account_type"] == "line_of_credit"]
        if not locs:
            st.info("Add a line-of-credit account first.")
        else:
            loc_by_name = {item["name"]: item for item in locs}
            with st.form("loan_event"):
                loc_name = st.selectbox("Line of credit", list(loc_by_name))
                event_date = st.date_input("Date", value=date.today())
                event_type = st.selectbox("Activity", ["draw", "principal_payment", "interest", "fee", "adjustment"])
                principal = st.number_input("Principal amount", min_value=0.0, step=100.0)
                interest = st.number_input("Interest amount", min_value=0.0, step=10.0)
                fee = st.number_input("Fee amount", min_value=0.0, step=10.0)
                notes = st.text_input("Notes")
                if st.form_submit_button("Record activity", type="primary"):
                    with db.connect(DB_PATH) as connection:
                        db.add_loan_event(connection, business_id=business_id,
                            loc_account_id=int(loc_by_name[loc_name]["id"]), event_date=event_date.isoformat(),
                            event_type=event_type, amount=principal, interest_amount=interest,
                            fee_amount=fee, notes=notes)
                    rerun()
    with db.connect(DB_PATH) as connection:
        events = db.list_loan_events(connection, business_id)
    if events:
        section_label("Credit activity history")
        st.dataframe(pd.DataFrame(events), hide_index=True, width="stretch")


elif page == "Export & Settings":
    page_header("Take your books with you",
                "Download a complete Excel workbook or prepare optional AI assistance without giving up control of decisions.",
                "Export & settings")
    with db.connect(DB_PATH) as connection:
        workbook = exporter.business_workbook(connection, business_id)
    st.download_button("Download current business workbook", data=workbook,
                       file_name=f"{db.slugify(business_name)}-books.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")
    st.caption("The export includes transactions, category totals, accounts, credit activity, learned rules, and import history.")
    st.divider()
    section_label("Optional AI assistance")
    st.write(ai_config.guidance())
    for provider, configured in ai_config.provider_status().items():
        st.write(f"{'✅' if configured else '○'} {provider}: {'key detected' if configured else 'not configured'}")
    st.info("Rule learning works locally without AI. A future AI feature can propose categories, but you will remain in control of final decisions.")
    st.caption(f"Database location: {DB_PATH}")
