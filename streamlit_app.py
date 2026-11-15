from __future__ import annotations

import os
import re
from html import escape
from datetime import date
from pathlib import Path
import base64
import hmac

import pandas as pd
import streamlit as st

from books import ai_config, backup, db, documents, exporter, importers, statements
from books import staff as staff_mod


APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BOOKS_DB_PATH", APP_DIR / "data" / "books.db"))
db.init_db(DB_PATH)
if "daily_backup_checked" not in st.session_state:  # automatic daily snapshot, kept for 14 days
    st.session_state["daily_backup_checked"] = True
    try:
        backup.maybe_daily_backup(DB_PATH)
    except Exception:  # a failed automatic backup must never block the app
        pass

ASSETS_DIR = APP_DIR / "assets"

PERSONAL_TAX_CATEGORIES = (
    "Charity", "Employment income", "Interest income", "Dividend income", "Other income",
    "Mortgage", "Property tax", "Investments", "Retirement", "Education / 529",
    "K-1 / business", "State tax", "Other",
)
PERSONAL_TAX_DOCUMENT_TYPES = (
    "Charity receipt", "W-2", "1099-INT", "1099-DIV", "1099-MISC", "1099-NEC",
    "1099-R", "1098 mortgage interest", "K-1", "Brokerage statement",
    "Property tax statement", "State tax refund", "529 statement", "Other",
)
PERSONAL_TAX_STATUSES = ("Expected", "Received", "Entered", "Not applicable")


def _asset_b64(name: str) -> str:
    try:
        return base64.b64encode((ASSETS_DIR / name).read_bytes()).decode()
    except OSError:
        return ""


LOGO_B64 = _asset_b64("rovar-logo.png")
_mark = ASSETS_DIR / "rovar-mark.png"
st.set_page_config(page_title="Ledgerly · Business Books", page_icon=str(_mark) if _mark.exists() else "◈", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown("""
<style>
  :root {
    --ink: #12141d; --muted: #6a6a6a; --line: #dde4ea; --paper: #ffffff;
    --canvas: #f2f5f6; --teal: #1778ba; --teal-soft: #e6f1f8;
    --gold: #f0b73f; --gold-soft: #fff4d6; --rose: #c05264; --rose-soft: #fdeff1;
  }
  @import url('https://fonts.googleapis.com/css2?family=Barlow:wght@300;400;600;700&family=Barlow+Condensed:wght@600;700&display=swap');
  html, body, [class*="css"] {font-family: Barlow, Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
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
    color:#fff !important; background:#0d3a5c !important;
    border:1px solid rgba(255,255,255,.18) !important;
    box-shadow:0 6px 18px rgba(20,42,67,.22) !important;
  }
  button[data-testid="stExpandSidebarButton"] span {color:#fff !important;}
  body:has([data-testid="stSidebarCollapseButton"] button[aria-expanded="true"])
    button[data-testid="stExpandSidebarButton"] {display:none !important;}
  [data-testid="stMainBlockContainer"] {max-width: 2000px; padding: 2.25rem 2rem 4rem;}
  [data-testid="stSidebar"] {background: linear-gradient(180deg, #0d3a5c 0%, #0b3150 62%, #12141d 100%); border-right: 0;}
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap: .72rem;}
  [data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {color: #dce7ef;}
  [data-testid="stSidebar"] [role="radiogroup"] {gap: .25rem;}
  [data-testid="stSidebar"] [role="radiogroup"] label {padding: .72rem .85rem; border-radius: 10px; transition: .15s ease;}
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child {display:none;}
  [data-testid="stSidebar"] [role="radiogroup"] label:hover {background: rgba(255,255,255,.08);}
  [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background: rgba(255,255,255,.14); box-shadow: inset 3px 0 0 #f0b73f;}
  [data-testid="stSidebar"] [data-baseweb="select"] > div {background: rgba(255,255,255,.1); border-color: rgba(255,255,255,.15);}
  [data-testid="stSidebar"] [data-testid="stExpander"] {border:0; background:transparent;}
  [data-testid="stSidebar"] [data-testid="stExpander"] summary {padding:.35rem .4rem; background:transparent !important;}
  [data-testid="stSidebar"] [data-testid="stExpander"] summary span, [data-testid="stSidebar"] [data-testid="stExpander"] summary svg {color:#9fc3dc !important;}
  [data-testid="stSidebar"] [data-testid="stExpander"] summary p {font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:#9fc3dc;}
  [data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] {gap:.15rem;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"], [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
    justify-content:flex-start; border:0; border-radius:10px; padding:.55rem .85rem; text-align:left;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] > div, [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] > div {justify-content:flex-start !important; width:100%;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] p, [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p {text-align:left !important; width:100%;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] {background:transparent !important;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] p {color:#dce7ef;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"]:hover {background:rgba(255,255,255,.08) !important;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {background:rgba(255,255,255,.14) !important; box-shadow:inset 3px 0 0 #f0b73f !important;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p {color:#fff; font-weight:650;}
  [data-testid="stSidebar"] hr {border-color: rgba(255,255,255,.12);}
  .brand {padding: .45rem .2rem 1.15rem; display:flex; align-items:center; gap:.8rem;}
  .brand-logo {background:#fff; border-radius:12px; padding:.55rem .8rem; box-shadow:0 8px 24px rgba(0,0,0,.22); display:flex; align-items:center;}
  .brand-logo img {height:40px; display:block;}
  .brand-mark {width:40px; height:40px; border-radius:12px; display:grid; place-items:center; color:#0d3a5c; background:#f0b73f; font-size:1.35rem; font-weight:900; box-shadow:0 8px 24px rgba(0,0,0,.22);}
  .brand-name {color:#fff; font-size:1.1rem; font-weight:760; letter-spacing:-.02em;}
  .brand-sub {color:#9fc3dc; font-size:.72rem; text-transform:uppercase; letter-spacing:.12em; margin-top:.1rem;}
  .page-head {margin:.15rem 0 1.6rem;}
  .eyebrow {font-size:.73rem; font-weight:750; color:var(--teal); text-transform:uppercase; letter-spacing:.14em; margin-bottom:.45rem;}
  .page-title {font-family: "Barlow Condensed", Barlow, sans-serif; font-weight:700; font-size:2.35rem; line-height:1.08; color:var(--ink); letter-spacing:-.035em; margin:0;}
  .page-sub {color:var(--muted); font-size:.98rem; margin-top:.55rem; max-width:760px; line-height:1.55;}
  .metric-card {background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:1.15rem 1.2rem; min-height:132px; box-shadow:0 4px 18px rgba(19,37,61,.045); position:relative; overflow:hidden;}
  .metric-card:after {content:""; position:absolute; width:70px; height:70px; border-radius:50%; right:-25px; top:-27px; background:var(--tint);}
  .metric-icon {width:32px; height:32px; border-radius:9px; display:grid; place-items:center; background:var(--tint); color:var(--accent); font-weight:800; margin-bottom:.75rem;}
  .metric-label {font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-weight:720;}
  .metric-value {font-family:"Barlow Condensed", Barlow, sans-serif; font-weight:700; font-size:clamp(1.35rem,2vw,1.75rem); color:var(--ink); letter-spacing:-.03em; margin-top:.2rem; white-space:nowrap;}
  .metric-note {font-size:.78rem; color:var(--muted); margin-top:.25rem;}
  .card {background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:1.25rem 1.35rem; box-shadow:0 4px 18px rgba(19,37,61,.04);}
  .transaction-card {background:linear-gradient(135deg,#0d3a5c,#1778ba); color:#fff; border-radius:18px; padding:1.45rem 1.55rem; box-shadow:0 12px 34px rgba(20,42,67,.18); margin:.4rem 0 1rem;}
  .transaction-card .meta {color:#bcdcf0; text-transform:uppercase; letter-spacing:.1em; font-size:.7rem; font-weight:700;}
  .transaction-card .desc {font-size:1.02rem; line-height:1.5; margin:.65rem 0 1rem; color:#f5fafb;}
  .transaction-card .amount {font-family:"Barlow Condensed", Barlow, sans-serif; font-weight:700; font-size:2rem; letter-spacing:-.02em;}
  .transaction-card .account {color:#cfe6f5; font-size:.84rem; margin-top:.2rem;}
  .section-kicker {font-size:.74rem; text-transform:uppercase; letter-spacing:.11em; color:var(--muted); font-weight:750; margin:1.75rem 0 .65rem;}
  div[data-testid="stForm"] {background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:1.2rem 1.3rem 1.35rem; box-shadow:0 4px 18px rgba(19,37,61,.04);}
  div[data-testid="stDataFrame"] {border:1px solid var(--line); border-radius:14px; overflow:hidden; box-shadow:0 3px 14px rgba(19,37,61,.035);}
  .stButton > button, .stDownloadButton > button {border-radius:10px; min-height:2.65rem; font-weight:680; border:1px solid #d8e0e8; background:#fff; color:var(--ink);}
  .stButton > button:hover, .stDownloadButton > button:hover {border-color:#9fb1c1; color:#0d3a5c;}
  .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {background:var(--teal); color:#fff; border-color:var(--teal); box-shadow:0 5px 15px rgba(23,120,186,.22);}
  .stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {background:#0b7069; border-color:#0d3a5c;}
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
        "teal": ("#1778ba", "#e6f1f8"), "navy": ("#0d3a5c", "#e6edf3"),
        "gold": ("#c98a10", "#fff4d6"), "rose": ("#b84e60", "#fdeff1"),
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


def period_picker(prefix: str, container=None) -> tuple[str | None, str | None]:
    """Year / all-time / custom range chooser; returns ISO start and end (or None for open ends)."""
    host = container or st
    this_year = date.today().year
    choice = host.selectbox("Period", ["All time", *[str(y) for y in range(this_year, this_year - 6, -1)], "Custom range"],
                            key=f"{prefix}_period")
    if choice == "All time":
        return None, None
    if choice == "Custom range":
        picked = host.date_input("Dates", value=(date(this_year, 1, 1), date.today()), key=f"{prefix}_dates")
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            return picked[0].isoformat(), picked[1].isoformat()
        return None, None
    return f"{choice}-01-01", f"{choice}-12-31"


def csv_download(label: str, frame: pd.DataFrame, file_stem: str, key: str) -> None:
    st.download_button(label, data=frame.to_csv(index=False).encode("utf-8"),
                       file_name=f"{db.slugify(business_name)}-{file_stem}.csv", mime="text/csv", key=key)


def render_loan_balances(loan_rows: list[dict], show_business: bool = False) -> None:
    """Two plain lists: who owes the business money, and who the business owes."""
    owed_to_us = sorted((r for r in loan_rows if r["owed_to_us"] > 0.004), key=lambda r: -r["owed_to_us"])
    we_owe = sorted((r for r in loan_rows if r["we_owe"] > 0.004), key=lambda r: -r["we_owe"])
    odd = [r for r in loan_rows if r["owed_to_us"] < -0.004 or r["we_owe"] < -0.004]
    c1, c2 = st.columns(2)
    with c1:
        metric_card("Owed to us", money(sum(r["owed_to_us"] for r in owed_to_us)), "Money others still owe us", "↗", "teal")
        st.markdown("**Who owes us**")
        if owed_to_us:
            frame = pd.DataFrame([{**({"Business": r["business"]} if show_business else {}),
                                   "Party": r["party"], "Amount": r["owed_to_us"]} for r in owed_to_us])
            st.dataframe(frame, hide_index=True, width="stretch",
                         column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        else:
            st.caption("Nobody owes us anything.")
    with c2:
        metric_card("We owe", money(sum(r["we_owe"] for r in we_owe)), "Money we still owe others", "↘", "rose")
        st.markdown("**Whom we owe**")
        if we_owe:
            frame = pd.DataFrame([{**({"Business": r["business"]} if show_business else {}),
                                   "Party": r["party"], "Amount": r["we_owe"]} for r in we_owe])
            st.dataframe(frame, hide_index=True, width="stretch",
                         column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        else:
            st.caption("We owe nobody anything.")
    if odd:
        with st.expander(f"{len(odd)} part(s) need a look: repayments larger than the loan on record"):
            st.caption("Usually a loan that was never recorded, or a payment that is not really a loan repayment.")
            st.dataframe(pd.DataFrame([{
                **({"Business": r["business"]} if show_business else {}), "Party": r["party"],
                "Problem": ("Repayments to us exceed loans made" if r["owed_to_us"] < -0.004
                            else "We repaid more than we borrowed"),
                "Excess": abs(min(r["owed_to_us"], r["we_owe"]))} for r in odd]),
                hide_index=True, width="stretch",
                column_config={"Excess": st.column_config.NumberColumn(format="$%.2f")})


def add_from_to(frame: pd.DataFrame, *, amount_col: str | None, direction_col: str | None, account_col: str,
                party_col: str, business: str) -> pd.DataFrame:
    """Add From / To columns: money in comes from the party into us, money out goes from us to the party."""
    frame = frame.copy()
    if direction_col:
        money_in = frame[direction_col].astype(str).str.lower().str.startswith("deposit")
    else:
        money_in = frame[amount_col].astype(float) >= 0
    us = frame[account_col].map(lambda account: f"{business} · {account}")
    party = frame[party_col].fillna("").replace("", "(not set)")
    frame["From"] = party.where(money_in, us)
    frame["To"] = us.where(money_in, party)
    return frame


def render_document_preview(key: str, business_id: int, current_id: int | None = None, jump=None):
    """One temporary upload box: look at an invoice, receipt or check while you update the transaction.

    Nothing is stored. Files stay in the upload box until you save, then that file is hidden.
    Returns (parsed details or None, file identity) for the file being viewed.
    """
    import base64
    import streamlit.components.v1 as components
    counter = st.session_state.get(f"doc_counter_{key}", 0)
    done = st.session_state.setdefault(f"doc_done_{key}", set())
    uploads = st.file_uploader(
        "Upload a PDF or image to view while you update (not stored)", type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True, key=f"doc_up_{key}_{counter}",
        help="Preview only. The file is not saved to your books and is forgotten when you save the decision.")
    waiting = [u for u in uploads or [] if (u.name, u.size) not in done]
    if not waiting:
        if uploads:
            st.caption("All uploaded files have been used. Upload more, or remove them above.")
        return None, None
    names = [u.name for u in waiting]
    chosen = waiting[0]
    if len(waiting) > 1:
        picked = st.selectbox(f"Viewing ({len(waiting)} files waiting)", names, key=f"doc_view_{key}_{counter}")
        chosen = waiting[names.index(picked)]
    data = chosen.getvalue()
    parsed = None
    if chosen.name.lower().endswith(".pdf"):
        parsed = parse_pdf_cached(data)
        encoded = base64.b64encode(data).decode()
        components.html(
            "<iframe id='f' style='width:100%;height:560px;border:1px solid #dde4ea;border-radius:10px'></iframe>"
            "<script>const b=Uint8Array.from(atob('" + encoded + "'),c=>c.charCodeAt(0));"
            "document.getElementById('f').src=URL.createObjectURL(new Blob([b],{type:'application/pdf'}));</script>",
            height=580)
        st.download_button("Open or download this PDF", data=data, file_name=chosen.name, mime="application/pdf",
                           key=f"doc_dl_{key}_{counter}_{chosen.name}")
        if parsed["has_text"]:
            with st.expander("Text read from the PDF"):
                st.text(documents.extract_text(data)[:3000])
            if jump is not None and parsed["total"]:
                with db.connect(DB_PATH) as connection:
                    candidates = [c for c in documents.match_candidates(connection, business_id, parsed)
                                  if c["score"] >= 5]
                best = candidates[0] if candidates else None
                if best and best["id"] != current_id:
                    st.info(f"This looks like transaction #{best['id']} · {best['transaction_date']} · "
                            f"{money(float(best['signed_amount']))} · {best['description'][:50]} ({best['why']}).")
                    jump(best)
                elif best:
                    st.caption("This document matches the transaction you are reviewing.")
        else:
            st.caption("This PDF has no readable text (a scan), so details can't be read from it. Use the preview.")
    else:
        st.image(data, width="stretch")
    return (parsed if parsed and parsed["has_text"] else None), (chosen.name, chosen.size)


def finish_document(key: str, ident) -> None:
    """Forget the file that was just used; when every file is used, reset the upload box."""
    if ident is None:
        return
    done = st.session_state.setdefault(f"doc_done_{key}", set())
    done.add(ident)


@st.cache_data(show_spinner=False, max_entries=200)
def parse_pdf_cached(data: bytes) -> dict:
    return documents.parse_document(documents.extract_text(data))


def apply_pdf_details(vendor_key: str, notes_key: str, vendor: str, note: str) -> None:
    if vendor:
        st.session_state[vendor_key] = vendor
    if note:
        st.session_state[notes_key] = note


def shift_staff_month(step: int) -> None:
    """Move the Staff & payroll month forward (+1) or back (-1) one month. Runs as a button callback."""
    options = staff_mod.recent_months(30)  # newest first
    current = st.session_state.get("staff_month")
    if current in options:
        st.session_state["staff_month"] = options[min(max(options.index(current) - step, 0), len(options) - 1)]


def rerun_dialog() -> None:
    """Refresh just the open dialog; fall back to a full rerun where fragments are not available."""
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


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


def log_workspace_reconciliation(workspace: dict, business_id: int) -> None:
    parsed = workspace["parsed"]
    with db.connect(DB_PATH) as connection:
        db.log_statement_reconciliation(
            connection, business_id=business_id, account_id=int(workspace["account_id"]),
            bank_name=parsed["bank"], account_last4=parsed["account_last4"],
            statement_date=parsed["statement_date"], statement_file_name=workspace.get("statement_name"),
            statement_check_total=float(parsed["check_total"]), statement_checks=parsed["checks"])


def go_to_check_image(name: str) -> None:
    st.session_state["active_check_image"] = name


def sync_check_direction(check_type_key: str, category_key: str, treatment_key: str) -> None:
    if st.session_state.get(category_key) == "Uncategorized":
        st.session_state[treatment_key] = (
            "Revenue" if st.session_state.get(check_type_key) == "deposit" else "Expense"
        )


def render_personal_tax_prep() -> None:
    page_header(
        "Personal tax preparation",
        "Keep a year-by-year checklist of personal tax documents and amounts, separate from every business ledger.",
        "Personal tax prep sheet",
    )
    with db.connect(DB_PATH) as connection:
        all_items = db.list_personal_tax_items(connection)
    current_year = date.today().year
    available_years = sorted(
        {current_year, current_year - 1, *(int(item["tax_year"]) for item in all_items)}, reverse=True)
    selected_year = st.selectbox("Tax year", available_years, key="personal_tax_year")

    with st.expander("Add a tax-prep item", expanded=not bool(all_items)):
        with st.form("add_personal_tax_item", clear_on_submit=True):
            a1, a2, a3 = st.columns(3)
            with a1:
                add_category = st.selectbox("Category", PERSONAL_TAX_CATEGORIES)
                custom_category = st.text_input("Custom category (optional)")
            with a2:
                add_document_type = st.selectbox("Document type", PERSONAL_TAX_DOCUMENT_TYPES)
                custom_document_type = st.text_input("Custom document type (optional)")
            with a3:
                add_status = st.selectbox("Status", PERSONAL_TAX_STATUSES)
                add_amount = st.number_input("Amount", min_value=0.0, step=100.0, format="%.2f")
            add_name = st.text_input(
                "Name / payer / charity",
                placeholder="Example: Johns Hopkins, UNICEF, Vanguard, mortgage lender",
            )
            add_notes = st.text_area("Notes", placeholder="Optional document details or follow-up")
            add_submitted = st.form_submit_button("Add to personal tax prep", type="primary")
            if add_submitted:
                try:
                    with db.connect(DB_PATH) as connection:
                        db.add_personal_tax_item(
                            connection,
                            tax_year=int(selected_year),
                            category=custom_category.strip() or add_category,
                            document_type=custom_document_type.strip() or add_document_type,
                            name=add_name,
                            amount=float(add_amount),
                            status=add_status,
                            notes=add_notes,
                        )
                    st.success("Personal tax-prep item added.")
                    rerun()
                except ValueError as exc:
                    st.error(str(exc))

    with db.connect(DB_PATH) as connection:
        year_items = db.list_personal_tax_items(connection, tax_year=int(selected_year))
    year_frame = pd.DataFrame(year_items)
    if year_frame.empty:
        st.info(f"No personal tax-prep items have been added for {selected_year}.")
        return

    section_label("Filter the prep sheet")
    f1, f2, f3 = st.columns(3)
    with f1:
        category_filter = st.multiselect(
            "Categories", sorted(year_frame["category"].unique()), placeholder="All categories")
    with f2:
        type_filter = st.multiselect(
            "Document types", sorted(year_frame["document_type"].unique()), placeholder="All document types")
    with f3:
        status_filter = st.multiselect(
            "Statuses", list(PERSONAL_TAX_STATUSES), placeholder="All statuses")
    filtered = year_frame.copy()
    if category_filter:
        filtered = filtered[filtered["category"].isin(category_filter)]
    if type_filter:
        filtered = filtered[filtered["document_type"].isin(type_filter)]
    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]

    total_amount = float(filtered["amount"].sum()) if not filtered.empty else 0.0
    received = int(filtered["status"].isin(["Received", "Entered"]).sum()) if not filtered.empty else 0
    expected = int((filtered["status"] == "Expected").sum()) if not filtered.empty else 0
    m1, m2, m3, m4 = st.columns(4)
    with m1: metric_card("Items", f"{len(filtered):,}", f"Tax year {selected_year}", "▤", "navy")
    with m2: metric_card("Recorded amount", money(total_amount), "Filtered sheet total", "$", "teal")
    with m3: metric_card("Received / entered", f"{received:,}", "Documents in hand", "✓", "gold")
    with m4: metric_card("Still expected", f"{expected:,}", "Follow-up list", "?", "rose")

    section_label("Personal tax prep sheet")
    display = filtered.rename(columns={
        "tax_year": "Year", "category": "Category", "document_type": "Type",
        "name": "Name / payer / charity", "amount": "Amount", "status": "Status", "notes": "Notes",
    })
    st.dataframe(
        display[["Year", "Category", "Type", "Name / payer / charity", "Amount", "Status", "Notes"]],
        hide_index=True, width="stretch",
        column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
    )
    summary = filtered.groupby("category", as_index=False).agg(Items=("id", "count"), Amount=("amount", "sum"))
    summary = summary.rename(columns={"category": "Category"}).sort_values("Amount", ascending=False)
    with st.expander("Category totals"):
        st.dataframe(
            summary, hide_index=True, width="stretch",
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
        )

    action1, action2 = st.columns(2)
    with action1:
        export_columns = ["tax_year", "category", "document_type", "name", "amount", "status", "notes"]
        st.download_button(
            "Download filtered sheet as CSV",
            data=filtered[export_columns].to_csv(index=False).encode("utf-8"),
            file_name=f"personal-tax-prep-{selected_year}.csv",
            mime="text/csv", width="stretch",
        )
    with action2:
        st.caption("This is an organization sheet, not tax advice. Confirm tax treatment with your tax professional.")

    with st.expander("Update or delete an item"):
        record_by_label = {
            f"{item['category']} · {item['document_type']} · {item['name']} · ID {item['id']}": item
            for item in year_items
        }
        record_label = st.selectbox("Item", list(record_by_label), key="personal_tax_edit_choice")
        record = record_by_label[record_label]
        item_id = int(record["id"])
        category_options = list(dict.fromkeys([*PERSONAL_TAX_CATEGORIES, str(record["category"])]))
        document_options = list(dict.fromkeys([*PERSONAL_TAX_DOCUMENT_TYPES, str(record["document_type"])]))
        with st.form(f"edit_personal_tax_{item_id}"):
            e1, e2, e3 = st.columns(3)
            with e1:
                edit_category = st.selectbox(
                    "Category", category_options, index=category_options.index(str(record["category"])))
                edit_year = st.number_input("Year", min_value=1900, max_value=2200, value=int(record["tax_year"]))
            with e2:
                edit_document = st.selectbox(
                    "Document type", document_options, index=document_options.index(str(record["document_type"])))
                edit_status = st.selectbox(
                    "Status", PERSONAL_TAX_STATUSES,
                    index=list(PERSONAL_TAX_STATUSES).index(str(record["status"]))
                    if str(record["status"]) in PERSONAL_TAX_STATUSES else 0)
            with e3:
                edit_name = st.text_input("Name / payer / charity", value=str(record["name"]))
                edit_amount = st.number_input(
                    "Amount", min_value=0.0, value=float(record["amount"]), step=100.0, format="%.2f")
            edit_notes = st.text_area("Notes", value=str(record.get("notes") or ""))
            if st.form_submit_button("Save changes", type="primary"):
                try:
                    with db.connect(DB_PATH) as connection:
                        db.update_personal_tax_item(
                            connection, item_id=item_id, tax_year=int(edit_year), category=edit_category,
                            document_type=edit_document, name=edit_name, amount=float(edit_amount),
                            status=edit_status, notes=edit_notes)
                    st.success("Personal tax-prep item updated.")
                    rerun()
                except ValueError as exc:
                    st.error(str(exc))
        confirm_delete = st.checkbox(
            "I confirm that I want to permanently delete this personal tax-prep item.",
            key=f"confirm_delete_personal_tax_{item_id}")
        if st.button(
            "Delete selected item", disabled=not confirm_delete,
            key=f"delete_personal_tax_{item_id}"):
            with db.connect(DB_PATH) as connection:
                deleted = db.delete_personal_tax_item(connection, item_id=item_id)
            if deleted:
                st.success("Personal tax-prep item deleted.")
                rerun()
            else:
                st.error("That item could not be found.")


with db.connect(DB_PATH) as connection:
    businesses = db.list_businesses(connection)

st.sidebar.markdown('<div class="brand-sub" style="margin:.2rem 0 .6rem .2rem">Ledgerly · Business books</div>',
                    unsafe_allow_html=True)
business_by_name = {item["name"]: item for item in businesses}
business_names = list(business_by_name)
if businesses:
    with db.connect(DB_PATH) as connection:
        default_business_id = db.get_setting(connection, "default_business_id", "")
    default_business_index = next(
        (index for index, name in enumerate(business_names)
         if str(business_by_name[name]["id"]) == default_business_id), 0)
    business_name = st.sidebar.selectbox("Business", business_names, index=default_business_index)
    business_id = int(business_by_name[business_name]["id"])
nav = {
    "▦  Dashboard": "Dashboard", "↗  Revenue & expense": "Revenue & Expense",
    "▣  Tax prep": "Tax Prep", "♙  Personal tax prep": "Personal Tax Prep",
    "⇧  Import transactions": "Import / Paste",
    "▤  Statements & checks": "Statements & Checks",
    "＄  Deposits": "Deposits", "✓  Review queue": "Review Queue", "≡  All transactions": "Transactions",
    "▥  Reports": "Reports", "☻  Staff & payroll": "Staff & Payroll", "☷  Parties": "Parties", "⌁  Categories & rules": "Categories & Rules",
    "◇  Accounts & credit": "Accounts & Credit",
    "⚙  Manage business": "Manage Business", "↓  Export & settings": "Export & Settings",
    "🛡  Admin & backup": "Admin & Backup",
}
if st.session_state.get("nav_choice") not in nav:
    st.session_state["nav_choice"] = "▦  Dashboard"
NAV_GROUPS = {
    "Overview": ["▦  Dashboard", "↗  Revenue & expense", "▥  Reports"],
    "Bookkeeping": ["⇧  Import transactions", "▤  Statements & checks", "＄  Deposits", "✓  Review queue",
                    "≡  All transactions"],
    "People & payroll": ["☻  Staff & payroll", "☷  Parties", "⌁  Categories & rules"],
    "Tax": ["▣  Tax prep", "♙  Personal tax prep"],
    "Setup": ["◇  Accounts & credit", "⚙  Manage business", "↓  Export & settings", "🛡  Admin & backup"],
}
nav_choice = st.session_state["nav_choice"]
for group_name, group_items in NAV_GROUPS.items():
    with st.sidebar.expander(group_name, expanded=nav_choice in group_items):
        for item in group_items:
            st.button(item, key=f"nav_btn_{item}", width="stretch", on_click=go_to, args=(item,),
                      type="primary" if item == nav_choice else "tertiary")
page = nav[nav_choice]

def render_admin() -> None:
    page_header("Protect your books",
                "Create, download and restore full-database backups. Backups cover every business in this database.",
                "Admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if admin_password and not st.session_state.get("admin_ok"):
        with st.form("admin_login"):
            entered = st.text_input("Admin password", type="password")
            if st.form_submit_button("Unlock admin tools", type="primary"):
                if hmac.compare_digest(entered.encode(), admin_password.encode()):
                    st.session_state["admin_ok"] = True
                    rerun()
                else:
                    st.error("That password is not correct.")
        return
    if not admin_password:
        st.warning("No admin password is set, so anyone who can open this app can restore or delete backups. "
                   "Set ADMIN_PASSWORD in your .env file and restart the container to lock these tools.")
    else:
        st.button("Lock admin tools", on_click=lambda: st.session_state.pop("admin_ok", None))

    backups = backup.list_backups(DB_PATH)
    live_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    m1, m2, m3 = st.columns(3)
    with m1: metric_card("Backups kept", f"{len(backups)}", "Stored beside the database", "▤", "teal")
    with m2: metric_card("Latest backup", backups[0]["created"].strftime("%b %d, %H:%M") if backups else "None yet",
                         backups[0]["kind"] if backups else "Create one below", "◷", "gold")
    with m3: metric_card("Database size", f"{live_size / 1024:,.0f} KB", str(DB_PATH.name), "$", "navy")

    section_label("Create a backup")
    c1, c2 = st.columns([1, 1])
    if c1.button("Back up now", type="primary", width="stretch"):
        created = backup.create_backup(DB_PATH, "manual")
        st.session_state["admin_message"] = f"Backup saved: {created.name}"
        rerun()
    c2.download_button(
        "Download a fresh backup", width="stretch",
        data=lambda: backup.backup_path(DB_PATH, backup.create_backup(DB_PATH, "download").name).read_bytes(),
        file_name=f"ledgerly-{date.today().isoformat()}.db", mime="application/octet-stream",
        help="Takes a snapshot and downloads it, so you can keep a copy off this machine.")
    if message := st.session_state.pop("admin_message", None):
        st.success(message)
    st.caption("An automatic backup is also taken the first time the app is opened each day; the 14 most recent "
               "automatic backups are kept. Manual and pre-restore backups are never deleted automatically.")

    section_label("Saved backups")
    if backups:
        st.dataframe(pd.DataFrame([{
            "File": row["name"], "Type": row["kind"], "Created": row["created"].strftime("%Y-%m-%d %H:%M:%S"),
            "Size (KB)": round(row["size"] / 1024, 1)} for row in backups]),
            hide_index=True, width="stretch")
        chosen_name = st.selectbox("Choose a backup", [row["name"] for row in backups], key="admin_backup_choice")
        a1, a2, a3 = st.columns(3)
        a1.download_button("Download", data=lambda: backup.backup_path(DB_PATH, chosen_name).read_bytes(),
                           file_name=chosen_name, mime="application/octet-stream", width="stretch")
        if a2.button("Restore this backup…", width="stretch"):
            restore_dialog(chosen_name)
        if a3.button("Delete…", width="stretch"):
            delete_backup_dialog(chosen_name)
    else:
        st.caption("No backups yet.")

    section_label("Restore from an uploaded file")
    uploaded = st.file_uploader("A Ledgerly .db backup", type=["db", "sqlite", "sqlite3"], key="admin_restore_upload")
    if uploaded is not None:
        temp = backup.backup_dir(DB_PATH) / "upload.partial"
        temp.write_bytes(uploaded.getvalue())
        try:
            counts = backup.validate_backup(temp)
            st.info(f"Valid backup: {counts['businesses']} business(es), {counts['accounts']} accounts, "
                    f"{counts['transactions']:,} transactions.")
            if st.button("Restore from this file…"):
                restore_dialog(None, upload_path=str(temp))
        except ValueError as exc:
            st.error(str(exc))
            temp.unlink(missing_ok=True)

    section_label("Copy categories and party rules between businesses")
    st.caption("Each business keeps its own categories and party bank-text rules. Use this to start one business "
               "from another's setup. Copies are one-way and never overwrite: names that already exist are skipped.")
    if len(businesses) < 2:
        st.caption("Create a second business to copy between them.")
    else:
        names = [item["name"] for item in businesses]
        by_name = {item["name"]: int(item["id"]) for item in businesses}
        c1, c2 = st.columns(2)
        source_name = c1.selectbox("Copy from", names, key="copy_source")
        target_name = c2.selectbox("Copy to", [n for n in names if n != source_name], key="copy_target")
        with db.connect(DB_PATH) as connection:
            source_categories = db.list_categories(connection, by_name[source_name])
            source_vendors = connection.execute(
                "SELECT id, name, match_pattern FROM vendors WHERE business_id = ? ORDER BY name",
                (by_name[source_name],)).fetchall()
        chosen_categories = st.multiselect(
            f"Categories to copy ({len(source_categories)} in {source_name})", [c["name"] for c in source_categories],
            default=[c["name"] for c in source_categories], key=f"copy_cats_{source_name}")
        vendor_labels = {f"{v['name']} — {v['match_pattern']}": int(v["id"]) for v in source_vendors}
        chosen_vendors = st.multiselect(
            f"Party bank-text rules to copy ({len(source_vendors)} in {source_name})", list(vendor_labels),
            default=list(vendor_labels), key=f"copy_vendors_{source_name}",
            help="Copying a rule also copies the category it uses if the target doesn't have it yet.")
        if st.button(f"Copy to {target_name}", type="primary", disabled=not (chosen_categories or chosen_vendors)):
            backup.create_backup(DB_PATH, "pre-copy")
            with db.connect(DB_PATH) as connection:
                cat_result = db.copy_categories(connection, by_name[source_name], by_name[target_name], chosen_categories)
                rule_result = db.copy_bank_text_rules(connection, by_name[source_name], by_name[target_name],
                                                      [vendor_labels[label] for label in chosen_vendors])
            st.success(f"Categories: {cat_result['copied']} copied, {cat_result['skipped']} already there. "
                       f"Party rules: {rule_result['copied']} copied, {rule_result['skipped']} already there. "
                       "A backup was taken first.")


@st.dialog("Restore this backup?")
def restore_dialog(name: str | None, upload_path: str | None = None) -> None:
    source = Path(upload_path) if upload_path else backup.backup_path(DB_PATH, name)
    counts = backup.validate_backup(source)
    st.write(f"This replaces **everything** in the live database with **{name or 'the uploaded file'}** "
             f"({counts['businesses']} business(es), {counts['transactions']:,} transactions).")
    st.caption("A safety backup of the current data is saved first, so this can be undone by restoring that one.")
    yes, no = st.columns(2)
    if yes.button("Restore", type="primary", width="stretch"):
        safety = backup.restore_backup(DB_PATH, source)
        db.init_db(DB_PATH)
        if upload_path:
            Path(upload_path).unlink(missing_ok=True)
        st.session_state["admin_message"] = f"Restored. Previous data saved as {safety.name}."
        rerun()
    if no.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Delete this backup?")
def delete_backup_dialog(name: str) -> None:
    st.write(f"Permanently delete **{name}**? This cannot be undone.")
    yes, no = st.columns(2)
    if yes.button("Delete", type="primary", width="stretch"):
        backup.delete_backup(DB_PATH, name)
        st.session_state["admin_message"] = f"Deleted {name}."
        rerun()
    if no.button("Cancel", width="stretch"):
        st.rerun()


def render_bank_text_rules() -> None:
    """Bank-text rules: a short phrase in the bank description sets the party, category and treatment."""
    st.caption("When a bank description contains the phrase, the transaction is filed under this party with the category and "
               "treatment below. Names here are parties, so they match the Parties list.")
    with db.connect(DB_PATH) as connection:
        categories = db.list_categories(connection, business_id)
        vendors = db.list_vendors(connection, business_id, include_inactive=True)
    if not categories:
        st.warning("Create at least one category before adding a rule.")
        return
    category_by_name = {item["name"]: item for item in categories}
    category_defaults = {item["name"]: item["default_treatment"] for item in categories}
    left, right = st.columns(2, gap="large")
    with left:
        section_label("Add a rule")
        new_vendor_name = st.text_input("Party (vendor / customer) name", key="new_vendor_name")
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
        if st.button("Add rule", type="primary", width="stretch"):
            try:
                with db.connect(DB_PATH) as connection:
                    _, applied = db.upsert_vendor(
                        connection, business_id=business_id, name=new_vendor_name,
                        match_pattern=new_vendor_pattern,
                        category_id=int(category_by_name[new_vendor_category]["id"]),
                        treatment=new_vendor_treatment, apply_existing=new_vendor_apply)
                st.success(f"Rule saved. {applied} waiting transaction(s) were classified.")
                rerun()
            except Exception as exc:
                st.error(str(exc))
    with right:
        section_label("Manage a rule")
        if not vendors:
            st.info("No rules yet. Save one during Review or add it here.")
        else:
            vendor_by_label = {
                f"{item['name']} · contains {item['match_pattern']}{' · inactive' if not item['active'] else ''}": item
                for item in vendors
            }
            vendor_label = st.selectbox("Rule", list(vendor_by_label))
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
                if st.form_submit_button("Save rule changes", width="stretch"):
                    try:
                        with db.connect(DB_PATH) as connection:
                            _, applied = db.upsert_vendor(
                                connection, business_id=business_id, vendor_id=int(vendor["id"]),
                                name=edit_vendor_name, match_pattern=edit_vendor_pattern,
                                category_id=int(category_by_name[edit_vendor_category]["id"]),
                                treatment=edit_vendor_treatment, active=edit_vendor_active,
                                apply_existing=edit_vendor_apply)
                        st.success(f"Rule updated. {applied} waiting transaction(s) were classified.")
                        rerun()
                    except Exception as exc:
                        st.error(str(exc))
    section_label("All rules")
    if vendors:
        vendor_frame = pd.DataFrame(vendors).rename(columns={
            "name": "Party", "match_pattern": "Description contains",
            "category_name": "Category", "treatment": "Treatment", "hit_count": "Rule matches",
            "active": "Active"})
        st.dataframe(vendor_frame[["Party", "Description contains", "Category", "Treatment", "Rule matches", "Active"]],
                     hide_index=True, width="stretch")


if page == "Admin & Backup":
    render_admin()
    st.stop()

if page == "Personal Tax Prep":
    render_personal_tax_prep()
    st.stop()

if not businesses:
    st.title("Create your first business")
    with st.form("first_business"):
        name = st.text_input("Business name")
        if st.form_submit_button("Create business", type="primary") and name.strip():
            with db.connect(DB_PATH) as connection:
                db.get_or_create_business(connection, name.strip())
            rerun()
    st.stop()

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

    dash_ids = [int(b["id"]) for b in businesses] if all_businesses else [business_id]
    business_name_by_id = {int(b["id"]): b["name"] for b in businesses}
    dash_loans, dash_vendors = [], []
    dash_loan_problems = 0
    with db.connect(DB_PATH) as connection:
        for dash_id in dash_ids:
            for row in db.loan_report(connection, dash_id):
                dash_loans.append({"business": business_name_by_id[dash_id], **row})
            for row in db.vendor_report(connection, dash_id):
                dash_vendors.append({"Business": business_name_by_id[dash_id], **row})
            dash_loan_problems += len(db.loan_direction_problems(connection, dash_id))
    section_label("Revenue and expense by vendor")
    if dash_vendors:
        vendor_dash = pd.DataFrame(dash_vendors).rename(columns={
            "party": "Vendor / party", "revenue": "Revenue", "expense": "Expense", "net": "Net",
            "transactions": "Transactions", "last_activity": "Last activity"})
        if all_businesses:
            vendor_dash = vendor_dash.groupby("Vendor / party", as_index=False).agg(
                Revenue=("Revenue", "sum"), Expense=("Expense", "sum"), Net=("Net", "sum"),
                Transactions=("Transactions", "sum"), **{"Last activity": ("Last activity", "max")})
        else:
            vendor_dash = vendor_dash.drop(columns=["Business"])
        top_n = st.slider("Vendors to show", 5, 100, 25, key="dash_vendor_count_25")
        for title, column in (("Revenue by vendor", "Revenue"), ("Expense by vendor", "Expense")):
            ranked = vendor_dash[vendor_dash[column] > 0].sort_values(column, ascending=False)
            shown = ranked.head(top_n)
            st.markdown(f"**{title}** · top {len(shown)} of {len(ranked)} · total {money(float(ranked[column].sum()))}"
                        f" · shown {money(float(shown[column].sum()))}")
            if shown.empty:
                st.caption(f"No {column.lower()} recorded yet.")
            else:
                st.dataframe(shown[["Vendor / party", column, "Transactions", "Last activity"]], hide_index=True, width="stretch",
                             height=min(35 * (len(shown) + 1) + 3, 940),
                             column_config={column: st.column_config.NumberColumn(format="$%.2f")})
        st.button("▥  Open vendor report", on_click=go_to, args=("▥  Reports",), key="dash_to_vendor")
    else:
        st.caption("No revenue or expense recorded yet.")
    section_label("Loans")
    if dash_loan_problems:
        w1, w2 = st.columns([4, 1])
        w1.warning(f"{dash_loan_problems} loan entr{'y is' if dash_loan_problems == 1 else 'ies are'} filed the wrong way "
                   "(for example money received marked as repaid by us, or the owner's own money filed as a loan), "
                   "so the balances below are not right yet.")
        w2.button("Fix them", on_click=go_to, args=("▥  Reports",), key="dash_fix_loans", type="primary",
                  help="Opens Reports. On the Loans tab, tick the fixes and press Apply.")
    if dash_loans:
        render_loan_balances(dash_loans, show_business=all_businesses)
        st.button("▥  Open loan reports", on_click=go_to, args=("▥  Reports",), key="dash_to_loans")
    else:
        st.caption("No loan activity recorded yet.")


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
    excluded_frame = year_frame[year_frame["treatment"].isin(["Transfer", "Loan draw", "Principal repayment", "Loan receivable", "Receivable repayment", "Owner contribution", "Owner draw", "Excluded"])]
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
                    "statement_name": statement_file.name,
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
        month_start = f"{str(parsed['statement_date'])[:7]}-01"
        with db.connect(DB_PATH) as connection:
            pending_deposits = db.list_unreconciled_deposits(
                connection, business_id, int(workspace["account_id"]), start=month_start,
                end=str(parsed["statement_date"]))
        if pending_deposits:
            st.warning(
                f"{len(pending_deposits)} credit(s) this month look like deposited checks "
                f"({money(sum(float(d['signed_amount']) for d in pending_deposits))}) and have no check images "
                "reconciled yet. Scroll to **Deposited checks** below.")
        log_col, log_note = st.columns([1, 3])
        if log_col.button("Log this statement", key="log_statement_now", width="stretch"):
            log_workspace_reconciliation(workspace, business_id)
            st.session_state["statement_log_message"] = "Statement logged for archiving."
            rerun()
        log_note.caption(f"Statement file: {workspace.get('statement_name') or 'unknown'} · "
                         "logged automatically each time you confirm a check.")
        if message := st.session_state.pop("statement_log_message", None):
            st.success(message)
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
                flat = statements.extract_check_images_with_text(uploaded.getvalue())
                if len(flat) <= 2:
                    # one check: show the largest image first, as before
                    extracted = statements.extract_check_images(uploaded.getvalue())
                    if extracted:
                        image_sets.append({"name": uploaded.name, "images": extracted})
                    continue
                st.info(f"“{uploaded.name}” contains {len(flat)} check images — more than one check. "
                        "It has been split so each check can be confirmed on its own.")
                per_check = st.radio(
                    f"Images per check in {uploaded.name}", [2, 1], horizontal=True,
                    index=0 if len(flat) % 2 == 0 else 1, key=f"images_per_check_{uploaded.name}",
                    format_func=lambda n: "2 (front and back)" if n == 2 else "1 (front only)")
                for position, group in enumerate(statements.group_check_images(flat, per_check), start=1):
                    guess = statements.match_text_to_check(checks, " ".join(text for _, text in group))
                    image_sets.append({"name": f"{uploaded.name} · check {position}",
                                       "images": [png for png, _ in group], "check_index": guess})

            uploaded_indexes = {
                matched for item in image_sets
                if (matched := statements.resolve_check_index(checks, item)) is not None
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
                       if checks and statements.resolve_check_index(checks, item) is None]
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
                if (idx := statements.resolve_check_index(checks, image_by_name[name])) is not None
                and not mapped_check(checks[idx])]
            if pending_names:
                following = [n for n in pending_names if names.index(n) > names.index(active_image_name)]
                target = (following or pending_names)[0]
                if target != active_image_name:
                    st.button(f"Next unmapped check →  {target}", on_click=go_to_check_image, args=(target,))
            elif checks:
                st.caption("No uploaded check image points at an unmapped check.")
            resolved_index = statements.resolve_check_index(checks, active_image) if checks else None
            suggested_index = resolved_index or 0
            guessed = bool(checks) and resolved_index is None
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
                        help="Selecting Loan chooses Loan receivable (money you lend out). Change the treatment if this is money you borrowed.")
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
                        st.text_input("From (us)", value=f"{business_name} · {selected_account_name}", disabled=True,
                                      key=f"check_from_{active_image_name}_{chosen['check_number']}")
                        payee = st.text_input(f"To · {counterparty_label}", key=payee_key,
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
                            log_workspace_reconciliation(workspace, business_id)
                            st.success(f"Check #{chosen['check_number']} was saved in the register.")
                            rerun()
        if st.button("Clear temporary PDF previews"):
            st.session_state.pop("statement_workspace", None)
            rerun()

    section_label("Deposited checks")
    st.caption("Checks you deposited (money coming in). Pick the bank deposit, add the check images, and enter each "
               "check — the amounts must add up to the deposit.")
    deposit_account = account_by_name[selected_account_name]
    dcol1, dcol2 = st.columns([1, 1])
    with db.connect(DB_PATH) as connection:
        all_credits = db.list_unreconciled_deposits(
            connection, business_id, int(deposit_account["id"]), checks_only=False)
    show_all_credits = dcol2.checkbox(
        "Show every credit, not just ones that look like deposited checks", key="deposit_show_all",
        help="ACH, wire and transfer credits are hidden by default.")
    credits = all_credits if show_all_credits else [
        row for row in all_credits if db.looks_like_check_deposit(row["description"])]
    months = sorted({row["transaction_date"][:7] for row in credits}, reverse=True)
    month_choice = dcol1.selectbox("Month", ["All months"] + months, key="deposit_month")
    if month_choice != "All months":
        credits = [row for row in credits if row["transaction_date"].startswith(month_choice)]
    if not credits:
        st.success("No unreconciled deposits for this account" + ("." if month_choice == "All months" else f" in {month_choice}."))
    else:
        credit_by_label = {
            f"#{row['id']} · {row['transaction_date']} · {money(float(row['signed_amount']))} · {row['description'][:70]}": row
            for row in credits}
        credit_labels = list(credit_by_label)
        st.caption("Click a row to select that deposit below.")
        credit_grid_key = f"deposit_grid_{selected_account_name}_{month_choice}_{show_all_credits}"
        credit_grid = st.dataframe(pd.DataFrame(credits).rename(columns={
            "id": "Transaction #", "transaction_date": "Date", "description": "Description",
            "signed_amount": "Amount", "treatment": "Treatment", "status": "Status"}),
            hide_index=True, width="stretch", key=credit_grid_key,
            on_select="rerun", selection_mode="single-row",
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        clicked = credit_grid.selection.rows
        if clicked and clicked[0] < len(credit_labels):
            clicked_label = credit_labels[clicked[0]]
            if st.session_state.get("deposit_grid_applied") != (credit_grid_key, clicked_label):
                st.session_state["deposit_grid_applied"] = (credit_grid_key, clicked_label)
                st.session_state["deposit_choice"] = clicked_label
        if st.session_state.get("deposit_choice") not in credit_by_label:
            st.session_state.pop("deposit_choice", None)
        deposit_label = st.selectbox("Deposit to reconcile", list(credit_by_label), key="deposit_choice")
        deposit = credit_by_label[deposit_label]
        deposit_id = int(deposit["id"])
        image_column, entry_column = st.columns([1.1, 1], gap="large")
        with image_column:
            deposit_files = st.file_uploader(
                "Images of the deposited checks (PDF, PNG or JPG)", type=["pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True, key=f"deposit_files_{deposit_id}")
            pictures_all: list[tuple[str, str, bytes]] = []
            for uploaded in deposit_files or []:
                if uploaded.name.lower().endswith(".pdf"):
                    found = statements.extract_check_images(uploaded.getvalue())[:6]
                    if not found:
                        st.info(f"No check image was found in {uploaded.name}.")
                else:
                    found = [uploaded.getvalue()]
                for index, picture in enumerate(found):
                    pictures_all.append((uploaded.name, "Front" if index == 0 else "Back" if index == 1 else f"Page {index + 1}",
                                         picture))
            if pictures_all:
                pos_key = f"deposit_image_pos_{deposit_id}"
                position = min(int(st.session_state.get(pos_key, 0)), len(pictures_all) - 1)
                nav_prev, nav_label, nav_next = st.columns([1, 2.2, 1])
                if nav_prev.button("◀ Previous", key=f"deposit_prev_{deposit_id}", width="stretch", disabled=position <= 0):
                    st.session_state[pos_key] = position - 1
                    rerun()
                if nav_next.button("Next ▶", key=f"deposit_next_{deposit_id}", width="stretch",
                                   disabled=position >= len(pictures_all) - 1):
                    st.session_state[pos_key] = position + 1
                    rerun()
                nav_label.markdown(f"<div style='text-align:center;padding-top:0.4rem'>Image {position + 1} of {len(pictures_all)}</div>",
                                   unsafe_allow_html=True)
                labels = [f"{i + 1}. {name} · {side}" for i, (name, side, _) in enumerate(pictures_all)]
                jump = st.selectbox("Jump to image", labels, index=position, key=f"deposit_jump_{deposit_id}_{position}",
                                    label_visibility="collapsed")
                if labels.index(jump) != position:
                    st.session_state[pos_key] = labels.index(jump)
                    rerun()
                shown_name, shown_side, shown_picture = pictures_all[position]
                st.image(shown_picture, caption=f"{shown_name} · {shown_side}", width="stretch")
                st.caption("Enter this check on the table row whose Image file is " + shown_name + ".")
            else:
                st.caption("Add check images to look at them one at a time. Cash needs no image: add a row with Type = Cash.")
        with entry_column:
            st.markdown(f"#### Deposit of {money(float(deposit['signed_amount']))} on {deposit['transaction_date']}")
            seed_key = f"deposit_seed_{deposit_id}"
            file_names = [item.name for item in deposit_files or []]
            table_key = (f"deposit_table_{deposit_id}_{st.session_state.get(seed_key, {}).get('version', 0)}_"
                         f"{abs(hash(tuple(file_names)))}")
            with db.connect(DB_PATH) as connection:
                prefill = db.suggest_deposit_check_details(connection, business_id, deposit_id)
            split_lines = []
            if deposit.get("status") == "split":
                with db.connect(DB_PATH) as connection:
                    split_lines = db.get_split_lines(connection, deposit_id)
            if split_lines:
                starter = pd.DataFrame([{
                    "Type": "Check", "Check #": "", "Received from": line["counterparty"] or "",
                    "Amount": abs(float(line["signed_amount"])), "Memo": line["notes"] or "",
                    "Image file": file_names[index] if index < len(file_names) else "",
                    "Category": line["category"] or "Uncategorized", "Treatment": line["treatment"]}
                    for index, line in enumerate(split_lines)])
            elif len(file_names) > 1:
                starter = pd.DataFrame([{
                    "Type": "Check", "Check #": "", "Received from": "", "Amount": None, "Memo": "", "Image file": name}
                    for name in dict.fromkeys(file_names)])
            else:
                starter = pd.DataFrame([{
                    "Type": "Check", "Check #": prefill.get("check_number") or "", "Received from": prefill.get("payer") or "",
                    "Amount": float(deposit["signed_amount"]),
                    "Memo": prefill.get("memo") or "", "Image file": file_names[0] if file_names else ""}])
            seed = st.session_state.get(seed_key)
            if seed:
                starter.loc[0, ["Check #", "Received from", "Memo"]] = [
                    seed.get("check_number") or "", seed["payer"], seed["memo"]]
            if split_lines:
                st.info("This deposit was split, so each row below is one line of the split with its own category and "
                        "treatment. Add the check numbers and images; amounts must still add up to the deposit.")
            elif prefill:
                st.caption(f"Pre-filled from your records: {prefill['reason']}. Edit anything that is not right.")
            st.caption(f"**From:** each check's payer  →  **To:** {business_name} · {selected_account_name}. "
                       "Add a row (＋ at the bottom of the table) for each extra check, or set Type = Cash for cash.")
            edited = st.data_editor(
                starter, key=table_key, num_rows="dynamic", hide_index=True, width="stretch",
                column_config={
                    "Type": st.column_config.SelectboxColumn(options=["Check", "Cash"], default="Check", required=True,
                                                             help="Cash needs no check number or image."),
                    "Received from": st.column_config.TextColumn("From (payer)"),
                    "Category": st.column_config.SelectboxColumn(options=["Uncategorized"] + list(category_by_name)),
                    "Treatment": st.column_config.SelectboxColumn(options=list(db.TREATMENTS[:-1])),
                    "Amount": st.column_config.NumberColumn(format="$%.2f", min_value=0.0, step=0.01),
                    "Image file": st.column_config.SelectboxColumn(options=[""] + file_names)})
            entered = edited.dropna(subset=["Amount"])
            entered_total = round(float(entered["Amount"].sum()), 2) if len(entered) else 0.0
            difference = round(float(deposit["signed_amount"]) - entered_total, 2)
            if abs(difference) < 0.005:
                st.success(f"Checks add up to the deposit ({money(entered_total)}).")
            else:
                st.warning(f"Checks add up to {money(entered_total)}; "
                           f"{money(abs(difference))} {'still to account for' if difference > 0 else 'too much'}.")
            d_category_key = f"deposit_category_{deposit_id}"
            d_treatment_key = f"deposit_treatment_{deposit_id}"
            multi_checks = len(entered) >= 2 and not split_lines
            if multi_checks:
                st.warning(f"{len(entered)} checks on one deposit: when you confirm, the deposit is marked **Needs split** "
                           "so each check can get its own category. Open it on All transactions and press ✂ Split…; "
                           "the lines will be pre-filled from these checks.")
            if not split_lines and not multi_checks:
                d_options = ["Uncategorized"] + list(category_by_name)
                d_defaults = {"Uncategorized": "Revenue", **{
                    name: item["default_treatment"] for name, item in category_by_name.items()}}
                st.session_state.setdefault(
                    d_category_key, prefill.get("category") if prefill.get("category") in category_by_name else "Uncategorized")
                st.session_state.setdefault(
                    d_treatment_key, prefill.get("treatment") if prefill.get("treatment") in db.TREATMENTS else "Revenue")
                st.selectbox("Category", d_options, key=d_category_key, on_change=sync_category_treatment,
                             args=(d_category_key, d_treatment_key, d_defaults))
                st.selectbox("Treatment", list(db.TREATMENTS), key=d_treatment_key,
                             help="Revenue for customer payments. Use Receivable repayment when a loan you made is being repaid, "
                                  "or Loan draw if the money is a loan to you.")
                chosen_treatment = st.session_state[d_treatment_key]
                chosen_category = st.session_state[d_category_key]
                if chosen_treatment != "Revenue" or chosen_category == "Internal transfer":
                    with db.connect(DB_PATH) as connection:
                        last_details = (db.last_deposit_details(
                            connection, business_id, treatment=chosen_treatment,
                            category=chosen_category if chosen_category in category_by_name else None,
                            exclude_transaction_id=deposit_id)
                            or db.last_deposit_details(connection, business_id, treatment=chosen_treatment,
                                                       exclude_transaction_id=deposit_id))
                    if last_details:
                        with st.container(border=True):
                            st.markdown(f"**Use details from the {last_details['reason']}?**")
                            st.caption(f"Received from: {last_details['payer'] or '—'} · Memo: {last_details['memo'] or '—'}")
                            if st.button("Fill the table with these details", key=f"deposit_fill_{deposit_id}"):
                                st.session_state[seed_key] = {
                                    **last_details, "version": st.session_state.get(seed_key, {}).get("version", 0) + 1}
                                rerun()
            if st.button("Confirm deposited checks", type="primary", width="stretch",
                         disabled=abs(difference) >= 0.005 or not len(entered), key=f"deposit_confirm_{deposit_id}"):
                d_category = "Uncategorized" if multi_checks else st.session_state.get(d_category_key, "Uncategorized")
                with db.connect(DB_PATH) as connection:
                    try:
                        db.confirm_deposit_checks(
                            connection, business_id=business_id, account_id=int(deposit_account["id"]),
                            transaction_id=deposit_id, bank_name=deposit_account.get("institution") or "",
                            account_last4=deposit_account.get("last4") or "",
                            deposited_checks=[{
                                "check_number": (f"CASH-{deposit_id}-{number}" if str(row.get("Type") or "") == "Cash"
                                                 else str(row["Check #"] or "")),
                                "payer": str(row["Received from"] or ""),
                                "amount": float(row["Amount"]),
                                "memo": str(row["Memo"] or "") or ("Cash deposit" if str(row.get("Type") or "") == "Cash" else ""),
                                "image_file": "" if str(row.get("Type") or "") == "Cash" else str(row["Image file"] or ""),
                                **({"category_id": (int(category_by_name[row["Category"]]["id"])
                                                    if row.get("Category") in category_by_name else None),
                                    "treatment": row.get("Treatment") or "Revenue"} if split_lines else {})}
                                for number, (_, row) in enumerate(entered.iterrows(), start=1)],
                            category_id=(int(category_by_name[d_category]["id"]) if d_category in category_by_name else None),
                            treatment=None if multi_checks else st.session_state.get(d_treatment_key, "Revenue"),
                            needs_split=multi_checks)
                        st.session_state["deposit_message"] = (
                            f"Deposit #{deposit_id} reconciled with {len(entered)} check(s)."
                            + (" It is marked Needs split: open it on All transactions and press ✂ Split…." if multi_checks else ""))
                    except ValueError as exc:
                        st.error(str(exc))
                        st.stop()
                rerun()
    if message := st.session_state.pop("deposit_message", None):
        st.success(message)

    section_label("Statement reconciliation log")
    with db.connect(DB_PATH) as connection:
        statement_log = db.list_statement_log(connection, business_id)
        statement_log_rows = db.statement_log_rows(connection, business_id)
    if statement_log:
        lf1, lf2, lf3, lf4 = st.columns([1.6, 1.2, 1, 1])
        log_search = lf1.text_input("Search statements", key="log_search", placeholder="File name, bank, account…")
        log_accounts = sorted({row["account"] for row in statement_log})
        log_account = lf2.selectbox("Account", ["All accounts"] + log_accounts, key="log_account")
        log_status = lf3.selectbox("Status", ["All"] + sorted({row["status"] for row in statement_log}), key="log_status")
        log_years = sorted({str(row["statement_date"])[:4] for row in statement_log}, reverse=True)
        log_year = lf4.selectbox("Year", ["All"] + log_years, key="log_year")
        def log_match(row: dict, file_key: str, status_key: str) -> bool:
            hay = " ".join(str(row.get(k) or "") for k in (file_key, "bank_name", "bank", "account", "account_last4")).lower()
            return ((not log_search.strip() or log_search.strip().lower() in hay)
                    and (log_account == "All accounts" or row["account"] == log_account)
                    and (log_status == "All" or row[status_key] == log_status)
                    and (log_year == "All" or str(row["statement_date"]).startswith(log_year)))
        shown_log = [row for row in statement_log if log_match(row, "statement_file_name", "status")]
        shown_log_rows = [row for row in statement_log_rows if log_match(row, "statement_file", "statement_status")]
        st.caption(f"Showing {len(shown_log):,} of {len(statement_log):,} statements")
        if shown_log:
            log_frame = pd.DataFrame(shown_log).rename(columns={
                "statement_file_name": "Statement file", "bank_name": "Bank", "account": "Account",
                "account_last4": "Ending", "statement_date": "Statement date", "checks_listed": "Checks listed",
                "checks_mapped": "Reconciled", "statement_check_total": "Statement total", "mapped_total": "Reconciled total",
                "deposits_reconciled": "Deposits reconciled", "deposit_total": "Deposit total",
                "status": "Status", "first_logged_at": "First logged", "updated_at": "Last updated"}).drop(columns=["id"])
            st.dataframe(log_frame, hide_index=True, width="stretch", column_config={
                "Statement total": st.column_config.NumberColumn(format="$%.2f"),
                "Reconciled total": st.column_config.NumberColumn(format="$%.2f"),
                "Deposit total": st.column_config.NumberColumn(format="$%.2f")})
            st.download_button(
                "Download log with every check (CSV)", type="primary",
                data=(add_from_to(pd.DataFrame(shown_log_rows), amount_col=None, direction_col="direction",
                                  account_col="account", party_col="counterparty", business=business_name)
                      if shown_log_rows else pd.DataFrame(shown_log_rows)).to_csv(index=False).encode("utf-8"),
                file_name=f"{db.slugify(business_name)}-statement-reconciliation-log.csv", mime="text/csv",
                help="One row per check and deposited check for the statements shown above, ready to archive next to the statement.")
        else:
            st.info("No statements match these filters.")
    else:
        st.caption("Statements appear here once you confirm a check or press “Log this statement”.")

    section_label("Confirmed check register")
    with db.connect(DB_PATH) as connection:
        register = db.list_check_register(connection, business_id)
    for entry in register:
        entry["split_state"] = ("Split" if entry.get("transaction_status") == "split"
                                else "Needs split" if int(entry.get("lines_on_transaction") or 0) >= 2 else "")
    total_register = len(register)
    if register:
        rf1, rf2, rf3, rf4, rf5, rf6 = st.columns([1.5, 1, 1, 1, 1, 1])
        reg_search = rf1.text_input("Search checks", key="reg_search", placeholder="Check #, payee, memo, amount…")
        reg_account = rf2.selectbox("Account", ["All accounts"] + sorted({r["account"] for r in register}), key="reg_account")
        reg_dir = rf3.selectbox("Direction", ["All", "Payments", "Deposits"], key="reg_dir")
        reg_treat = rf4.selectbox("Treatment", ["All"] + sorted({r["treatment"] for r in register if r["treatment"]}), key="reg_treat")
        reg_year = rf5.selectbox("Year", ["All"] + sorted({str(r["cleared_date"])[:4] for r in register}, reverse=True), key="reg_year")
        reg_split = rf6.selectbox("Split", ["All", "Needs split", "Split"], key="reg_split",
                                  help="Needs split: the bank transaction has 2 or more lines in the register and isn't split yet.")
        needle = reg_search.strip().lower().replace(",", "").replace("$", "")
        def reg_match(r: dict) -> bool:
            hay = " ".join(str(r.get(k) or "") for k in (
                "check_number", "payee", "memo", "account", "category", "treatment", "source_file_name")).lower()
            hay += f" {float(r['amount']):.2f} {int(float(r['amount']))}"
            return ((not needle or needle in hay)
                    and (reg_account == "All accounts" or r["account"] == reg_account)
                    and (reg_dir == "All" or r["check_type"] == ("payment" if reg_dir == "Payments" else "deposit"))
                    and (reg_treat == "All" or r["treatment"] == reg_treat)
                    and (reg_year == "All" or str(r["cleared_date"]).startswith(reg_year))
                    and (reg_split == "All" or r["split_state"] == reg_split))
        register = [r for r in register if reg_match(r)]
        grid_key = f"check_register_grid_{abs(hash((reg_search, reg_account, reg_dir, reg_treat, reg_year, reg_split)))}"
        st.caption(f"Showing {len(register):,} of {total_register:,} checks · {money(sum(float(r['amount']) for r in register))}")
    if register:
        register_frame = pd.DataFrame(register).rename(columns={
            "cleared_date": "Cleared", "written_date": "Written", "check_number": "Check #",
            "amount": "Amount", "payee": "Counterparty", "memo": "Memo", "bank_name": "Bank",
            "account": "Account", "category": "Category", "treatment": "Treatment",
            "check_type": "Direction",
            "transaction_id": "Transaction #", "source_file_name": "Source file", "split_state": "Split"})
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
                st.session_state.pop(grid_key, None)
                rerun()
            if no.button("Cancel", width="stretch"):
                st.rerun()

        st.caption("Select a row in the grid to delete it.")
        register_frame = add_from_to(register_frame, amount_col=None, direction_col="Direction", account_col="Account",
                                     party_col="Counterparty", business=business_name)
        grid = st.dataframe(
            register_frame[["Cleared", "Written", "Check #", "Direction", "From", "To", "Amount", "Counterparty", "Memo",
                            "Bank", "Account", "Category", "Treatment", "Split", "Transaction #", "Source file"]],
            hide_index=True, width="stretch", key=grid_key,
            on_select="rerun", selection_mode="single-row",
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        selected_rows = grid.selection.rows
        if st.button("🗑  Delete selected check", disabled=not selected_rows, key="delete_check_register_button"):
            confirm_delete_dialog(register[selected_rows[0]])
    elif total_register:
        st.info("No checks match these filters.")
    else:
        st.caption("No checks have been confirmed yet.")


elif page == "Deposits":
    page_header("Account for every deposit",
                "Cash, ATM, mobile and wire credits in one place. Tick the ones that belong together and classify them in one step.",
                "Deposits")
    with db.connect(DB_PATH) as connection:
        accounts = db.list_accounts(connection, business_id)
        categories = db.list_categories(connection, business_id)
    f1, f2, f3, f4 = st.columns([1.2, 1, 1, 1])
    acct_options = {"All accounts": None, **{a["name"]: int(a["id"]) for a in accounts}}
    acct_pick = f1.selectbox("Account", list(acct_options), key="dep_account")
    kind_pick = f2.selectbox("Deposit type", ["All", "Cash / ATM", "Mobile / check", "Wire / ACH", "Other deposit", "Other credit"], key="dep_kind")
    state_pick = f3.selectbox("Show", ["Needs classifying", "Already classified", "Everything"], key="dep_state")
    year_pick = f4.selectbox("Year", ["All"] + sorted({str(d)[:4] for d in [date.today().year, date.today().year - 1]}, reverse=True), key="dep_year")
    start = end = None
    if year_pick != "All":
        start, end = f"{year_pick}-01-01", f"{year_pick}-12-31"
    with db.connect(DB_PATH) as connection:
        deposits = db.list_deposits(connection, business_id, account_id=acct_options[acct_pick], start=start, end=end)
    if kind_pick != "All":
        deposits = [d for d in deposits if d["kind"] == kind_pick]
    if state_pick == "Needs classifying":
        deposits = [d for d in deposits if d["status"] == "needs_review"]
    elif state_pick == "Already classified":
        deposits = [d for d in deposits if d["status"] != "needs_review"]

    total = sum(float(d["signed_amount"]) for d in deposits)
    m1, m2 = st.columns(2)
    m1.metric("Deposits shown", f"{len(deposits):,}")
    m2.metric("Total", money(total))
    if not deposits:
        st.success("No deposits match these filters.")
        st.stop()

    frame = pd.DataFrame([{
        "Select": False, "ID": d["id"], "Date": d["transaction_date"], "Account": d["account"],
        "Type": d["kind"], "Description": d["description"], "Amount": float(d["signed_amount"]),
        "Accounted as": d["treatment"] if d["status"] != "needs_review" else "— not yet —",
        "From / source": d["counterparty"] or "", "Note": d["notes"] or "",
        "Check images": "✓" if d["linked_checks"] else "",
    } for d in deposits])
    pick_all = st.checkbox("Select all shown", key="dep_select_all")
    if pick_all:
        frame["Select"] = True
    edited = st.data_editor(
        frame, hide_index=True, width="stretch", height=420,
        key=f"dep_editor_{pick_all}_{acct_pick}_{kind_pick}_{state_pick}_{year_pick}",
        disabled=[c for c in frame.columns if c != "Select"],
        column_config={"ID": None, "Amount": st.column_config.NumberColumn(format="$%.2f"),
                       "Select": st.column_config.CheckboxColumn("✓", width="small")})
    chosen = edited[edited["Select"]]
    chosen_ids = [int(i) for i in chosen["ID"]]
    chosen_total = float(chosen["Amount"].sum()) if len(chosen) else 0.0
    st.markdown(f"**{len(chosen_ids)} selected · {money(chosen_total)}**")

    with st.container(border=True):
        st.markdown("**Classify the selected deposits**")
        explain = {
            "Revenue": "Sales or income. Counts in revenue and the P&L.",
            "Loan draw": "Money you borrowed. Not income. Enter who lent it.",
            "Transfer": "Moved between your own accounts. Not income.",
            "Owner contribution": "Money you put into the business. Not income, not a loan.",
            "Receivable repayment": "Someone repaying a loan you made. Not income. Enter who repaid.",
            "Revenue refund": "A customer refund reversal. Reduces revenue.",
            "Expense refund": "A vendor refunded you. Reduces expenses.",
            "Excluded": "Leave out of the books entirely.",
        }
        c1, c2 = st.columns(2)
        treatment = c1.selectbox("Treatment", list(db.DEPOSIT_TREATMENTS), key="dep_treatment")
        c1.caption(explain[treatment])
        labels = {"Revenue": "Received from / customer", "Loan draw": "Loan received from",
                  "Transfer": "Transferred from", "Owner contribution": "Contributed by",
                  "Receivable repayment": "Repaid by", "Revenue refund": "Refund paid to",
                  "Expense refund": "Refund received from", "Excluded": "Source (optional)"}
        is_loan = treatment in ("Loan draw", "Receivable repayment")
        with db.connect(DB_PATH) as connection:
            party_names = db.known_parties(connection, business_id)
        if is_loan:
            heading = ("Loan FROM (lender who gave you this money)" if treatment == "Loan draw"
                       else "Loan TO (borrower repaying you)")
            c2.markdown(f"**{heading}**")
            party_pick = c2.selectbox("Choose existing party", ["＋ New name…"] + party_names, key=f"dep_party_pick_{treatment}")
            counterparty = (c2.text_input("New party name", key=f"dep_party_new_{treatment}")
                            if party_pick == "＋ New name…" else party_pick)
        else:
            counterparty = c2.text_input(labels[treatment], key=f"dep_party_{treatment}")
        category_id = None
        related_id = None
        if treatment == "Revenue":
            revenue_cats = [c for c in categories if c["default_treatment"] in ("Revenue", "Revenue refund")] or categories
            cat_by_name = {c["name"]: int(c["id"]) for c in revenue_cats}
            cat_pick = c1.selectbox("Revenue category", ["— No category —"] + list(cat_by_name), key="dep_category")
            category_id = cat_by_name.get(cat_pick)
        fill_from_records = False
        if treatment == "Transfer":
            fill_from_records = st.checkbox(
                "Fill the other account from my records (matching opposite entry or earlier similar transfers)",
                value=True, key="dep_fill_transfer")
            if fill_from_records and chosen_ids:
                with db.connect(DB_PATH) as connection:
                    guesses = [(i, db.suggest_transfer_counterpart(connection, business_id, i)) for i in chosen_ids]
                shown = [{"Deposit": f"{money(float(edited.loc[edited['ID'] == i, 'Amount'].iloc[0]))} · "
                                      f"{edited.loc[edited['ID'] == i, 'Date'].iloc[0]}",
                          "From account": (g or {}).get("related_account_name") or "— no match, set below —",
                          "Why": (g or {}).get("reason", "")} for i, g in guesses]
                st.dataframe(pd.DataFrame(shown), hide_index=True, width="stretch")
            rel = {"— None —": None, **{a["name"]: int(a["id"]) for a in accounts}}
            related_id = rel[c2.selectbox("From account (overrides the match above)", list(rel), key="dep_related")]
        note = st.text_input("Note (optional)", key="dep_note", placeholder="e.g. cash sales week of Apr 14")
        if st.button(f"Classify {len(chosen_ids)} deposit(s) as {treatment}", type="primary",
                     disabled=not chosen_ids, width="stretch"):
            if treatment in ("Loan draw", "Receivable repayment") and not counterparty.strip():
                st.error("Enter who the loan is with so the balance can be tracked.")
            else:
                with db.connect(DB_PATH) as connection:
                    done = db.classify_deposits(
                        connection, business_id=business_id, transaction_ids=chosen_ids,
                        treatment=treatment, counterparty=counterparty, category_id=category_id,
                        related_account_id=related_id, notes=note,
                        fill_transfer_from_records=fill_from_records)
                st.session_state["dep_message"] = f"Classified {done} deposit(s) as {treatment}."
                rerun()
    if st.session_state.get("dep_message"):
        st.success(st.session_state.pop("dep_message"))

    with db.connect(DB_PATH) as connection:
        every = db.list_deposits(connection, business_id, start=start, end=end)
    summary: dict[str, list[float]] = {}
    for d in every:
        key = d["treatment"] if d["status"] != "needs_review" else "Not yet classified"
        item = summary.setdefault(key, [0, 0.0]); item[0] += 1; item[1] += float(d["signed_amount"])
    st.markdown("**Where all deposits stand**")
    st.dataframe(pd.DataFrame([{"Accounted as": k, "Deposits": v[0], "Total": v[1]} for k, v in sorted(summary.items())]),
                 hide_index=True, width="stretch",
                 column_config={"Total": st.column_config.NumberColumn(format="$%.2f")})


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
    label = st.selectbox("Transaction", list(item_by_label), key="review_txn_pick")
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
        def review_jump(best: dict) -> None:
            target = next((lbl for lbl, item in item_by_label.items() if int(item["id"]) == int(best["id"])), None)
            if target:
                st.button("Go to that transaction", key=f"review_jump_{best['id']}",
                          on_click=lambda: st.session_state.__setitem__("review_txn_pick", target))
            else:
                st.caption("That transaction is not in this review queue.")
        pdf_info, pdf_ident = render_document_preview("review", business_id, int(row["id"]), review_jump)
    with right:
        if pdf_info:
            with st.container(border=True):
                st.markdown("**Read from the PDF you are viewing**")
                st.caption(" · ".join(bit for bit in [
                    f"Vendor: {pdf_info['vendor']}" if pdf_info["vendor"] else "",
                    f"Invoice {pdf_info['invoice']}" if pdf_info["invoice"] else "",
                    f"Total {money(pdf_info['total'])}" if pdf_info["total"] else "",
                    f"Date {pdf_info['dates'][0]}" if pdf_info["dates"] else ""] if bit) or "No details found.")
                if pdf_info["total"] and abs(pdf_info["total"] - abs(float(row["signed_amount"]))) >= 0.005:
                    st.warning(f"The PDF total ({money(pdf_info['total'])}) differs from this transaction "
                               f"({money(abs(float(row['signed_amount'])))}). Check it is the right document.")
                note_text = " · ".join(bit for bit in [
                    f"Invoice {pdf_info['invoice']}" if pdf_info["invoice"] else "",
                    f"dated {pdf_info['dates'][0]}" if pdf_info["dates"] else ""] if bit)
                st.button("Use these details", key=f"review_use_pdf_{row['id']}", on_click=apply_pdf_details,
                          args=(f"review_vendor_{row['id']}", f"review_notes_{row['id']}", pdf_info["vendor"], note_text),
                          help="Fills the From / To name and the note below. You can still change them before saving.")
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
        related_key = f"review_related_{row['id']}"
        transfer_guess = None
        if treatment == "Transfer":
            with db.connect(DB_PATH) as connection:
                transfer_guess = db.suggest_transfer_counterpart(connection, business_id, int(row["id"]))
            if (transfer_guess and transfer_guess["related_account_name"] in related_options
                    and st.session_state.get(related_key, "— None —") == "— None —"
                    ):
                st.session_state[related_key] = transfer_guess["related_account_name"]
        related_name = st.selectbox("Related account", list(related_options), key=related_key,
                                     help="Use for transfers, loan draws, principal repayments, and loans receivable.")
        if transfer_guess:
            st.caption(f"Pre-filled from your records: {transfer_guess['reason']}.")
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
        money_in_row = float(row["signed_amount"]) >= 0
        our_side = f"{business_name} · {row['account']}"
        ft1, ft2 = st.columns(2)
        if money_in_row:
            vendor_name = ft1.text_input("From (who sent it)", value=suggested_pattern, key=f"review_vendor_{row['id']}",
                                         help=f"{counterparty_label}. Saved as the party on this transaction.")
            ft2.text_input("To (us)", value=our_side, disabled=True, key=f"review_to_{row['id']}")
        else:
            ft1.text_input("From (us)", value=our_side, disabled=True, key=f"review_from_{row['id']}")
            vendor_name = ft2.text_input("To (who received it)", value=suggested_pattern, key=f"review_vendor_{row['id']}",
                                         help=f"{counterparty_label}. Saved as the party on this transaction.")
        save_vendor = st.checkbox("Save this counterparty mapping", value=True,
                                  key=f"review_save_vendor_{row['id']}",
                                  help="Future matching transactions will receive this category and treatment automatically.")
        apply_existing = st.checkbox("Apply to matching transactions already waiting", value=True,
                                     key=f"review_apply_{row['id']}")
        notes = st.text_input("Optional note", key=f"review_notes_{row['id']}")
        if st.button("Save decision & learn", type="primary", width="stretch", key=f"review_save_{row['id']}"):
            category_id = int(category_by_name[category_name]["id"]) if category_name in category_by_name else None
            direction_problem = db.loan_direction_error(float(row["signed_amount"]), treatment)
            if direction_problem:
                st.error(direction_problem)
            elif save_vendor and category_id is None:
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
                    if treatment in db.LOAN_TREATMENTS and vendor_name.strip():
                        db.set_transaction_counterparty(
                            connection, business_id=business_id, transaction_id=int(row["id"]),
                            counterparty=vendor_name)
                finish_document("review", pdf_ident)
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
    frame["counterparty"] = frame["counterparty"].fillna("")
    frame["loan_role"] = frame["treatment"].map(db.LOAN_ROLES).fillna("")
    frame = add_from_to(frame, amount_col="signed_amount", direction_col=None, account_col="account",
                        party_col="counterparty", business=business_name)
    frame["Debit / Credit"] = frame["signed_amount"].map(lambda v: "Credit" if float(v) >= 0 else "Debit")
    frame["Split"] = [("🔒 Split original" if status == "split" else f"↳ Line of #{int(parent)}" if pd.notna(parent)
                       else "Needs split" if int(linked or 0) >= 2 else "")
                      for status, parent, linked in zip(frame["status"], frame["split_parent_id"], frame["linked_checks"])]
    f1, f2, f3, f4, f5 = st.columns(5)
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
        status_options = sorted(frame["status"].dropna().unique())
        status_filters = st.multiselect("Statuses", status_options, key="txn_status_filter",
                                        default=["needs_review"] if "needs_review" in status_options else [],
                                        placeholder="All statuses")
    with f5:
        side_filters = st.multiselect("Debit / Credit", ["Debit", "Credit"], placeholder="Both")
    valid_dates = frame["transaction_date"].dropna()
    date_value = (valid_dates.min().date(), valid_dates.max().date()) if not valid_dates.empty else (date.today(), date.today())
    dr1, dr2 = st.columns([2, 1])
    selected_dates = dr1.date_input("Transaction date range", value=date_value)
    split_filters = dr2.multiselect("Split status", ["Needs split", "🔒 Split original", "↳ Split line"],
                                    placeholder="All transactions",
                                    help="Needs split: a bank transaction with 2 or more checks in the check register that "
                                         "hasn't been split yet. Split original: locked until its split is reverted. "
                                         "Split line: one of the lines a split created.")
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
    if side_filters:
        filtered = filtered[filtered["Debit / Credit"].isin(side_filters)]
    if split_filters:
        keep = pd.Series(False, index=filtered.index)
        if "Needs split" in split_filters:
            keep |= filtered["Split"] == "Needs split"
        if "🔒 Split original" in split_filters:
            keep |= filtered["Split"] == "🔒 Split original"
        if "↳ Split line" in split_filters:
            keep |= filtered["Split"].str.startswith("↳")
        filtered = filtered[keep]
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
        filtered = filtered[(filtered["transaction_date"].dt.date >= start_date) &
                            (filtered["transaction_date"].dt.date <= end_date)]
    sort1, sort2 = st.columns([2, 1])
    sortable_columns = {
        "Date": "transaction_date", "Account": "account", "Description": "description",
        "Amount": "signed_amount", "Debit / Credit": "Debit / Credit", "Category": "category", "Treatment": "treatment",
        "Status": "status", "Reference": "source_reference", "Notes": "notes",
        "Counterparty / loan party": "counterparty", "Loan role": "loan_role", "From": "From", "To": "To",
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
    category_by_name = {item["name"]: item for item in categories}
    def render_split_log() -> None:
        with db.connect(DB_PATH) as connection:
            log = db.list_split_log(connection, business_id)
        with st.expander(f"Split log ({len(log)})"):
            if not log:
                st.caption("No transactions have been split yet. Open a transaction and press ✂ Split….")
                return
            st.dataframe(pd.DataFrame([{
                "When": row["created_at"][:19].replace("T", " "), "Action": row["action"], "#": row["parent_id"],
                "Transaction": row["parent_summary"], "Amount": row["parent_amount"], "Lines": row["lines"],
                "Detail": row["detail"], "Now": "split" if row["current_status"] == "split" else "not split"}
                for row in log]), hide_index=True, width="stretch",
                column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
            active = {}
            for row in log:
                if row["current_status"] == "split":
                    active.setdefault(row["parent_id"], row["parent_summary"])
            if active:
                pick = st.selectbox("Revert a split", list(active), format_func=lambda pid: f"#{pid} · {active[pid]}",
                                    key="split_log_revert_pick")
                if st.button("Revert this split", key="split_log_revert"):
                    with db.connect(DB_PATH) as connection:
                        removed = db.revert_split(connection, business_id=business_id, transaction_id=int(pick))
                    st.session_state["txn_saved_message"] = f"Reverted split #{pick}: {removed} line(s) removed."
                    rerun()

    st.session_state.setdefault("txn_edit_window", True)
    window_mode = st.toggle("Edit in a window: click a row to open it", key="txn_edit_window",
                            help="Streamlit tables cannot detect a double-click, so a single click on any cell opens the edit window. "
                                 "Turn this off for the spreadsheet grid and bulk actions.")
    if window_mode:
        pick_columns = ["id", "transaction_date", "description", "signed_amount", "Debit / Credit", "category",
                        "treatment", "From", "To", "counterparty", "status", "Split", "notes", "account"]
        st.caption("Click any cell in a row to edit it in a window, with Previous / Next to move through the list. "
                   "Turn the switch off for the spreadsheet grid and bulk actions.")
        nav_ids = [int(value) for value in filtered["id"].tolist()]
        st.session_state["txn_nav_ids"] = nav_ids
        if st.session_state.pop("txn_clear_pick", False):
            st.session_state["txn_pick_grid"] = {"selection": {"rows": [], "columns": [], "cells": []}}
            st.session_state["txn_pick_seen"] = None
        pick_grid = st.dataframe(
            filtered[pick_columns].rename(columns={"id": "#"}), hide_index=True, width="stretch", height=650,
            on_select="rerun", selection_mode=["single-cell", "single-row"], key="txn_pick_grid",
            column_config={"signed_amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
                           "description": st.column_config.TextColumn(width="large")})

        def close_txn_dialog() -> None:
            st.session_state.pop("txn_dialog_id", None)
            st.session_state["txn_clear_pick"] = True

        def render_split_panel(txn: dict, transaction_id: int, amount: float) -> None:
            is_split = txn["status"] == "split"
            total_abs = round(abs(amount), 2)
            money_in = amount >= 0
            st.markdown("#### Split this transaction" if not is_split else "#### This transaction is split")
            with st.expander("📎 View a document"):
                render_document_preview(f"split_{transaction_id}", business_id)
            st.caption("The lines you enter here become the source for revenue and expense; the original bank "
                       "transaction is kept but left out of the reports. Nothing is lost: Revert restores it, and every "
                       "change is written to the Split log.")
            if is_split:
                with db.connect(DB_PATH) as connection:
                    locked_lines = db.get_split_lines(connection, transaction_id)
                st.warning(f"🔒 **Original bank transaction, locked.** It is split into {len(locked_lines)} lines, and "
                           "those lines are what the reports use. It cannot be edited. To change it, revert the split "
                           "(this deletes the lines), then split it again.")
                st.dataframe(pd.DataFrame([{
                    "Line #": line["id"], "Amount": abs(float(line["signed_amount"])),
                    "Category": line["category"] or "Uncategorized", "Treatment": line["treatment"],
                    "From / To": line["counterparty"] or "", "Notes": line["notes"] or ""} for line in locked_lines]),
                    hide_index=True, width="stretch",
                    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
                sure = st.checkbox("I understand the split lines will be deleted", key=f"txd_revert_sure_{transaction_id}")
                r1, r2 = st.columns(2)
                if r1.button("Revert split", type="primary", width="stretch", disabled=not sure,
                             help="Deletes the lines and restores the transaction as it was before the split."):
                    with db.connect(DB_PATH) as connection:
                        removed = db.revert_split(connection, business_id=business_id, transaction_id=transaction_id)
                    st.session_state.pop("txn_split_mode", None)
                    st.toast(f"Reverted: {removed} line(s) removed")
                    rerun_dialog()
                if r2.button("Close", width="stretch", key=f"txd_locked_close_{transaction_id}"):
                    close_txn_dialog()
                    st.rerun()
                return
            names = list(category_by_name)
            with db.connect(DB_PATH) as connection:
                existing = db.get_split_lines(connection, transaction_id) if is_split else []
            default_treatment = "Revenue" if money_in else "Expense"
            if existing:
                starter = pd.DataFrame([{
                    "Amount": abs(float(l["signed_amount"])), "Category": l["category"] or "Uncategorized",
                    "Treatment": l["treatment"], "From / To": l["counterparty"] or "", "Notes": l["notes"] or ""}
                    for l in existing])
            else:
                with db.connect(DB_PATH) as connection:
                    check_lines = db.deposit_check_lines(connection, transaction_id)
                if len(check_lines) >= 2:
                    st.info(f"Pre-filled from the {len(check_lines)} checks recorded for this deposit. "
                            "Choose each line's category and treatment.")
                    starter = pd.DataFrame([{
                        "Amount": float(line["amount"]),
                        "Category": line["category"] if line["category"] in category_by_name else "Uncategorized",
                        "Treatment": line["treatment"] if line["treatment"] in db.TREATMENTS[:-1] else default_treatment,
                        "From / To": line["payee"] or "",
                        "Notes": (f"Check #{line['check_number']}" if line["check_number"] and not str(line["check_number"]).startswith(("DEP-", "CASH-"))
                                  else "Cash" if str(line["check_number"]).startswith("CASH-") else "") +
                                 (f" {line['memo']}" if line["memo"] and line["memo"] != "Cash deposit" else "")}
                        for line in check_lines])
                else:
                    starter = pd.DataFrame([{"Amount": None, "Category": "Uncategorized", "Treatment": default_treatment,
                                             "From / To": "", "Notes": ""} for _ in range(2)])
            edited_lines = st.data_editor(
                starter, key=f"txd_split_{transaction_id}_{len(existing)}_{len(starter)}", num_rows="dynamic", hide_index=True,
                width="stretch",
                column_config={
                    "Amount": st.column_config.NumberColumn(format="$%.2f", min_value=0.0, step=0.01),
                    "Category": st.column_config.SelectboxColumn(options=["Uncategorized"] + names),
                    "Treatment": st.column_config.SelectboxColumn(options=list(db.TREATMENTS[:-1])),
                    "From / To": st.column_config.TextColumn(
                        "From (who sent it)" if money_in else "To (who received it)"),
                })
            filled = edited_lines.dropna(subset=["Amount"])
            line_total = round(float(filled["Amount"].sum()), 2) if len(filled) else 0.0
            remaining = round(total_abs - line_total, 2)
            if abs(remaining) < 0.005:
                st.success(f"The lines add up to {money(total_abs)}.")
            else:
                st.warning(f"The lines add up to {money(line_total)}; "
                           f"{money(abs(remaining))} {'still to place' if remaining > 0 else 'too much'}.")
            lines = []
            problems = []
            for number, (_, row) in enumerate(filled.iterrows(), start=1):
                category_name = str(row["Category"] or "Uncategorized")
                category = category_by_name.get(category_name)
                line_treatment = row["Treatment"] if isinstance(row["Treatment"], str) and row["Treatment"] else (
                    category["default_treatment"] if category else default_treatment)
                error = db.loan_direction_error(amount / abs(amount) * float(row["Amount"]), line_treatment) if amount else None
                if error:
                    problems.append(f"Line {number}: {error}")
                lines.append({"amount": float(row["Amount"]), "category_id": int(category["id"]) if category else None,
                              "treatment": line_treatment, "counterparty": str(row["From / To"] or ""),
                              "notes": str(row["Notes"] or "")})
            for problem in problems:
                st.error(problem)
            s1, s2, s3 = st.columns(3)
            if s1.button("Save split" if not is_split else "Save changes", type="primary", width="stretch",
                         disabled=abs(remaining) >= 0.005 or len(lines) < 2 or bool(problems)):
                try:
                    with db.connect(DB_PATH) as connection:
                        db.split_transaction(connection, business_id=business_id, transaction_id=transaction_id, lines=lines)
                    st.session_state.pop("txn_split_mode", None)
                    st.toast(f"Split #{transaction_id} into {len(lines)} lines")
                    rerun_dialog()
                except ValueError as exc:
                    st.error(str(exc))
            if is_split:
                if s2.button("Revert split", width="stretch",
                             help="Deletes the lines and restores the transaction as it was before the split."):
                    with db.connect(DB_PATH) as connection:
                        removed = db.revert_split(connection, business_id=business_id, transaction_id=transaction_id)
                    st.session_state.pop("txn_split_mode", None)
                    st.toast(f"Reverted: {removed} line(s) removed")
                    rerun_dialog()
            elif s2.button("Back", width="stretch"):
                st.session_state.pop("txn_split_mode", None)
                rerun_dialog()
            if s3.button("Close", width="stretch", key=f"txd_split_close_{transaction_id}"):
                close_txn_dialog()
                st.rerun()

        @st.dialog("Edit transaction", width="large", on_dismiss=close_txn_dialog)
        def edit_transaction_dialog() -> None:
            ids = st.session_state.get("txn_nav_ids", [])
            transaction_id = int(st.session_state.get("txn_dialog_id", 0))
            with db.connect(DB_PATH) as connection:
                txn = db.get_transaction(connection, transaction_id)
            if not txn or int(txn["business_id"]) != business_id:
                st.error("That transaction could not be found.")
                return
            position = ids.index(transaction_id) if transaction_id in ids else 0
            prev_col, label_col, next_col = st.columns([1, 2, 1])
            if prev_col.button("◀ Previous", width="stretch", disabled=position <= 0):
                st.session_state["txn_dialog_id"] = ids[position - 1]
                st.session_state.pop("txn_split_mode", None)
                rerun_dialog()
            label_col.markdown(f"<div style='text-align:center;padding-top:0.4rem'>#{transaction_id} · "
                               f"{position + 1} of {len(ids)}</div>", unsafe_allow_html=True)
            if next_col.button("Next ▶", width="stretch", disabled=position >= len(ids) - 1):
                st.session_state["txn_dialog_id"] = ids[position + 1]
                st.session_state.pop("txn_split_mode", None)
                rerun_dialog()
            amount = float(txn["signed_amount"])
            ours = f"{business_name} · {txn['account_name']}"
            suffix = f"_{transaction_id}"
            st.markdown(f"**{txn['transaction_date']}** · {money(amount)} · {txn['description']}")
            is_child = bool(txn.get("split_parent_id"))
            if txn["status"] == "split" or st.session_state.get("txn_split_mode") == transaction_id:
                render_split_panel(txn, transaction_id, amount)
                return
            if is_child:
                st.info(f"This is one line of the split of transaction #{txn['split_parent_id']}. "
                        "Its amount is fixed. To change the split itself, open the locked original and revert it first.")
            fr, to = st.columns(2)
            if amount >= 0:
                party = fr.text_input("From (who sent it)", value=txn["counterparty"] or "", key="txd_party" + suffix)
                to.text_input("To (us)", value=ours, disabled=True, key="txd_us" + suffix)
            else:
                fr.text_input("From (us)", value=ours, disabled=True, key="txd_us" + suffix)
                party = to.text_input("To (who received it)", value=txn["counterparty"] or "", key="txd_party" + suffix)
            d1, d2 = st.columns(2)
            cat_options = ["Uncategorized"] + list(category_by_name)
            current_cat = txn["category_name"] if txn["category_name"] in category_by_name else "Uncategorized"
            category_choice = d1.selectbox("Category", cat_options, index=cat_options.index(current_cat),
                                           key="txd_cat" + suffix)
            treatment_options = list(db.TREATMENTS[:-1])
            current_treatment = txn["treatment"] if txn["treatment"] in treatment_options else treatment_options[0]
            if (txn["treatment"] not in treatment_options and category_choice in category_by_name):
                current_treatment = category_by_name[category_choice]["default_treatment"]
            treatment_choice = d2.selectbox("Treatment", treatment_options, index=treatment_options.index(current_treatment),
                                            key="txd_treat" + suffix)
            related_names = ["— None —"] + [a["name"] for a in accounts if int(a["id"]) != int(txn["account_id"])]
            related_now = txn["related_account_name"] if txn["related_account_name"] in related_names else "— None —"
            related_choice = st.selectbox("Related account (transfers and loans)", related_names,
                                          index=related_names.index(related_now), key="txd_rel" + suffix)
            note = st.text_area("Notes (for loans: why it was given or taken)", value=txn["notes"] or "", height=90,
                                key="txd_note" + suffix)
            with st.expander("📎 View a document"):
                render_document_preview(f"edit_{transaction_id}", business_id)
            remember = st.checkbox("Remember this category and treatment for similar transactions", value=False,
                                   key="txd_remember" + suffix)
            problem = db.loan_direction_error(amount, treatment_choice)
            if problem:
                st.error(problem)

            def save_current() -> None:
                related_id = next((int(a["id"]) for a in accounts if a["name"] == related_choice), None)
                category_id = None if category_choice == "Uncategorized" else int(category_by_name[category_choice]["id"])
                with db.connect(DB_PATH) as connection:
                    if remember and category_id is not None:
                        db.classify_transaction(connection, transaction_id, category_id=category_id,
                                                treatment=treatment_choice, related_account_id=related_id,
                                                notes=note.strip() or None, apply_existing=False)
                    else:
                        db.update_transaction_classification(connection, transaction_id, category_id=category_id,
                                                             treatment=treatment_choice, related_account_id=related_id,
                                                             notes=note.strip() or None)
                    db.set_transaction_counterparty(connection, business_id=business_id, transaction_id=transaction_id,
                                                    counterparty=party)

            b1, b2, b4, b3 = st.columns(4)
            if b1.button("Save", width="stretch", disabled=bool(problem)):
                save_current()
                st.toast(f"Saved #{transaction_id}")
                rerun_dialog()
            if b2.button("Save & next ▶", type="primary", width="stretch",
                         disabled=bool(problem) or position >= len(ids) - 1):
                save_current()
                st.toast(f"Saved #{transaction_id}")
                st.session_state["txn_dialog_id"] = ids[position + 1]
                rerun_dialog()
            if b4.button("✂ Split…", width="stretch", disabled=is_child,
                         help="Split this transaction into several lines, each with its own category."):
                st.session_state["txn_split_mode"] = transaction_id
                rerun_dialog()
            if b3.button("Close", width="stretch"):
                close_txn_dialog()
                st.rerun()

        picked_position = (pick_grid.selection.cells[0][0] if pick_grid.selection.cells
                           else pick_grid.selection.rows[0] if pick_grid.selection.rows else None)
        if picked_position is not None:
            picked = int(filtered.iloc[picked_position]["id"])
            seen = picked
            if st.session_state.get("txn_pick_seen") != seen:
                st.session_state["txn_pick_seen"] = seen
                st.session_state["txn_dialog_id"] = picked
                edit_transaction_dialog()
            elif st.session_state.get("txn_dialog_id"):
                edit_transaction_dialog()
        elif st.session_state.get("txn_dialog_id"):
            edit_transaction_dialog()
        if st.session_state.get("txn_saved_message"):
            st.success(st.session_state.pop("txn_saved_message"))
        render_split_log()
        st.stop()
    section_label("Editable transaction grid")
    st.caption("Check rows for bulk changes. Edit Category, Treatment, Counterparty or the From / To of the other party directly; copy/paste and drag-fill work like a spreadsheet. "
               "For loans, Counterparty is who you borrowed from or lent to — the Loan role column shows which.")
    category_names = [item["name"] for item in categories]
    category_by_name = {item["name"]: item for item in categories}
    select_all_visible = st.checkbox("Check all filtered transactions", value=False,
                                     help="Selects every transaction matching the current search and filters.")
    editor_columns = ["id", "transaction_date", "account", "description", "From", "To", "signed_amount", "Debit / Credit", "category",
                      "treatment", "loan_role", "counterparty", "status", "Split", "source_reference", "notes"]
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
        disabled=["id", "transaction_date", "account", "description", "signed_amount", "Debit / Credit", "Split",
                  "loan_role", "status", "source_reference", "notes"],
        column_order=["Select", "transaction_date", "description", "signed_amount", "Debit / Credit",
                      "category", "treatment", "From", "To", "loan_role", "counterparty", "status", "Split",
                      "source_reference", "notes", "account"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", help="Select rows for a bulk category change"),
            "transaction_date": st.column_config.TextColumn("Date"),
            "signed_amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
            "category": st.column_config.SelectboxColumn("Category", options=["Uncategorized"] + category_names,
                                                           required=True),
            "treatment": st.column_config.SelectboxColumn("Treatment", options=list(db.TREATMENTS[:-1]),
                                                            required=True),
            "loan_role": st.column_config.TextColumn("Loan role", help="Borrowed from, Repaid to, Lent to or Repaid by"),
            "From": st.column_config.TextColumn("From", help="Money in: edit this to set who sent it. Money out: your own account (not editable)."),
            "To": st.column_config.TextColumn("To", help="Money out: edit this to set who received it. Money in: your own account (not editable)."),
            "counterparty": st.column_config.TextColumn(
                "Counterparty / loan party", help="Who you paid or received from. For loans: the lender or borrower."),
        },
    )
    changed_ids = []
    counterparty_changed_ids = []
    for transaction_id, edited_row in edited.iterrows():
        original_row = editor_source.loc[transaction_id]
        if (edited_row["category"] != original_row["category"] or
                edited_row["treatment"] != original_row["treatment"]):
            changed_ids.append(int(transaction_id))
        party_column = "From" if float(original_row["signed_amount"]) >= 0 else "To"
        new_party = str(edited_row["counterparty"] or "").strip()
        if new_party == str(original_row["counterparty"] or "").strip():
            side_value = str(edited_row[party_column] or "").strip()
            if side_value != str(original_row[party_column] or "").strip():
                new_party = "" if side_value == "(not set)" else side_value
                edited.loc[transaction_id, "counterparty"] = new_party
        if new_party != str(original_row["counterparty"] or "").strip():
            counterparty_changed_ids.append(int(transaction_id))
    split_parents = {int(t) for t in editor_source.index if editor_source.loc[t, "Split"] == "🔒 Split original"}
    changed_ids = [t for t in changed_ids if t not in split_parents]
    counterparty_changed_ids = [t for t in counterparty_changed_ids if t not in split_parents]
    unsaved_total = len(set(changed_ids) | set(counterparty_changed_ids))
    selected_ids = [int(transaction_id) for transaction_id, row in edited.iterrows() if bool(row["Select"])]
    save1, save2 = st.columns([1, 2])
    with save1:
        if st.button(f"Save {unsaved_total:,} edited row(s)", type="primary", width="stretch",
                     disabled=not unsaved_total):
            saved = 0
            bad_direction = [
                f"#{tid}: {msg}" for tid in changed_ids
                if (msg := db.loan_direction_error(float(editor_source.loc[tid]["signed_amount"]),
                                                   str(edited.loc[tid]["treatment"])))]
            if bad_direction:
                st.error("Nothing was saved. " + " ".join(bad_direction))
                st.stop()
            with db.connect(DB_PATH) as connection:
                for transaction_id in counterparty_changed_ids:
                    db.set_transaction_counterparty(
                        connection, business_id=business_id, transaction_id=transaction_id,
                        counterparty=str(edited.loc[transaction_id]["counterparty"] or ""))
                    saved += 1
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
                    saved += 1 if transaction_id not in counterparty_changed_ids else 0
            st.success(f"Saved {saved} row(s). Category choices were learned as local rules.")
            rerun()
    with save2:
        st.caption(f"{len(selected_ids):,} row(s) selected for bulk actions · {unsaved_total:,} unsaved row edit(s)")
    section_label("Bulk category action")
    bulk1, bulk2, bulk3 = st.columns([2, 2, 1])
    with bulk1:
        bulk_category = st.selectbox("Set category", ["— Choose category —", "— Clear category —"] + category_names)
    with bulk2:
        bulk_treatment = st.selectbox("Treatment", ["Use category default"] + list(db.TREATMENTS[:-1]))
    with bulk3:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if st.button("Apply to selected", width="stretch", disabled=not selected_ids or bulk_category == "— Choose category —"):
            skipped_direction = 0
            with db.connect(DB_PATH) as connection:
                for transaction_id in selected_ids:
                    if bulk_category == "— Clear category —":
                        db.update_transaction_classification(connection, transaction_id, category_id=None)
                    else:
                        chosen_category = category_by_name[bulk_category]
                        chosen_treatment = (chosen_category["default_treatment"] if bulk_treatment == "Use category default"
                                            else bulk_treatment)
                        if transaction_id in split_parents:
                            skipped_direction += 1
                            continue
                        if db.loan_direction_error(float(editor_source.loc[transaction_id]["signed_amount"]), chosen_treatment):
                            skipped_direction += 1
                            continue
                        db.classify_transaction(connection, transaction_id,
                                                category_id=int(chosen_category["id"]),
                                                treatment=chosen_treatment, apply_existing=False)
            action = "cleared categories from" if bulk_category == "— Clear category —" else f"set {bulk_category} on"
            st.success(f"Successfully {action} {len(selected_ids) - skipped_direction} transaction(s).")
            if skipped_direction:
                st.warning(f"{skipped_direction} row(s) skipped: that loan treatment points the wrong way for the money.")
            rerun()
    if st.session_state.get("txn_saved_message"):
        st.success(st.session_state.pop("txn_saved_message"))
    render_split_log()
    with st.expander("＋ Add a transaction category"):
        with st.form("transaction_add_category", clear_on_submit=True):
            new_category_name = st.text_input("Category name")
            new_category_treatment = st.selectbox("Default treatment", list(db.TREATMENTS[:-1]))
            if st.form_submit_button("Add category", type="primary") and new_category_name.strip():
                with db.connect(DB_PATH) as connection:
                    db.get_or_create_category(connection, business_id, new_category_name.strip(), new_category_treatment)
                st.success(f"Added {new_category_name.strip()}.")
                rerun()


elif page == "Reports":
    page_header("Loans, exclusions and vendor reports",
                "Loan positions by party, everything kept out of profit and loss, and revenue and expense by vendor or party.",
                "Reports")
    r_start, r_end = period_picker("reports")
    tab_loans, tab_excluded, tab_vendor, tab_margin = st.tabs(["Loans", "Excluded from P&L", "By vendor / party", "Margin"])
    with db.connect(DB_PATH) as connection:
        loan_rows = db.loan_report(connection, business_id, r_start, r_end)
        loan_ledger_rows = db.loan_ledger(connection, business_id, r_start, r_end)
        vendor_rows = db.vendor_report(connection, business_id, r_start, r_end)

    with tab_loans:
        with db.connect(DB_PATH) as connection:
            direction_problems = db.loan_direction_problems(connection, business_id)
        if direction_problems:
            st.warning(f"{len(direction_problems)} loan entr{'y needs' if len(direction_problems) == 1 else 'ies need'} fixing. "
                       "Money received marked as repaid by us, or the owner's own money filed as a loan, will never net "
                       "against the real loans. For the owner's money use Owner contribution (money in) and "
                       "Owner draw (money out): neither is income, expense or a loan.")
            fix_frame = pd.DataFrame([{
                "Fix": True, "Date": p["date"], "Account": p["account"], "Description": p["description"],
                "Amount": p["signed_amount"], "Marked as": p["treatment"], "Problem": p["problem"],
                "Change to": p["suggested"], "Party": p["counterparty"] or ""} for p in direction_problems])
            fix_frame.index = [p["id"] for p in direction_problems]
            fixed = st.data_editor(
                fix_frame, key="loan_direction_editor", width="stretch",
                disabled=["Date", "Account", "Description", "Amount", "Marked as", "Problem"],
                column_config={
                    "Amount": st.column_config.NumberColumn(format="$%.2f"),
                    "Description": st.column_config.TextColumn(width="large"),
                    "Problem": st.column_config.TextColumn(width="medium"),
                    "Change to": st.column_config.SelectboxColumn(
                        "Change to", options=list(db.LOAN_TREATMENTS) + ["Owner contribution", "Owner draw"], required=True,
                        help="Must match the direction: money in or money out."),
                    "Party": st.column_config.TextColumn("Party (lender / borrower / owner)")})
            if st.button("Apply the ticked fixes", type="primary", key="apply_loan_fixes"):
                try:
                    with db.connect(DB_PATH) as connection:
                        count = db.fix_loan_rows(connection, business_id, [
                            {"id": int(tid), "treatment": row["Change to"], "counterparty": row["Party"]}
                            for tid, row in fixed.iterrows() if row["Fix"]])
                    st.success(f"Fixed {count} loan entr{'y' if count == 1 else 'ies'}.")
                    rerun()
                except Exception as exc:
                    st.error(str(exc))
        render_loan_balances(loan_rows)
        if not loan_rows:
            st.info("No loan activity in this period.")
        else:
            def _status(open_amount: float) -> str:
                return "Settled" if abs(open_amount) < 0.005 else ("Check: repaid more than lent" if open_amount < 0 else "Open")
            usd = st.column_config.NumberColumn(format="$%.2f")
            lent_rows = [r for r in loan_rows if r["lent"] or r["repaid_to_us"]]
            borrowed_rows = [r for r in loan_rows if r["borrowed"] or r["repaid_by_us"]]
            section_label("Money we lent: lent to whom, repaid by whom")
            if lent_rows:
                lent_frame = pd.DataFrame([{
                    "Lent to": r["party"], "We lent": r["lent"], "Repaid to us by them": r["repaid_to_us"],
                    "Still owes us": r["owed_to_us"], "Status": _status(r["owed_to_us"])} for r in lent_rows])
                st.dataframe(lent_frame, hide_index=True, width="stretch",
                             column_config={c: usd for c in ("We lent", "Repaid to us by them", "Still owes us")})
                csv_download("Download money we lent (CSV)", lent_frame, "loans-we-lent", "dl_loans_lent")
            else:
                st.caption("We lent no money in this period.")
            section_label("Money we borrowed: borrowed from whom, repaid to whom")
            if borrowed_rows:
                borrowed_frame = pd.DataFrame([{
                    "Borrowed from": r["party"], "We borrowed": r["borrowed"], "We repaid them": r["repaid_by_us"],
                    "We still owe": r["we_owe"], "Status": _status(r["we_owe"])} for r in borrowed_rows])
                st.dataframe(borrowed_frame, hide_index=True, width="stretch",
                             column_config={c: usd for c in ("We borrowed", "We repaid them", "We still owe")})
                csv_download("Download money we borrowed (CSV)", borrowed_frame, "loans-we-borrowed", "dl_loans_borrowed")
            else:
                st.caption("We borrowed no money in this period.")
            st.caption("\"Check\" means repayments are larger than the loan on record: usually a loan that was never recorded, "
                       "or a payment that is not really a loan repayment.")
            section_label("Loan transactions")
            ledger_frame = pd.DataFrame(loan_ledger_rows).rename(columns={
                "date": "Date", "party": "Party", "role": "Role", "treatment": "Treatment", "amount": "Amount",
                "account": "Account", "description": "Description", "source": "Source", "notes": "Notes"})
            ledger_frame.index = [f"{k}:{i}" for k, i in zip(ledger_frame["kind"], ledger_frame["id"])]
            us_label = ledger_frame["Account"].map(lambda account: f"{business_name} ({account})")
            money_in = ledger_frame["Treatment"].isin(["Loan draw", "Receivable repayment"])
            ledger_frame["From"] = ledger_frame["Party"].where(money_in, us_label)
            ledger_frame["To"] = us_label.where(money_in, ledger_frame["Party"])
            ledger_frame["What happened"] = ledger_frame["Treatment"].map({
                "Loan draw": "Loan received", "Principal repayment": "Loan repaid by us",
                "Loan receivable": "Loan made by us", "Receivable repayment": "Loan repaid to us"})
            party_pick = st.selectbox("Party", ["All parties"] + sorted(ledger_frame["Party"].unique()), key="loan_party_filter")
            if party_pick != "All parties":
                ledger_frame = ledger_frame[ledger_frame["Party"] == party_pick].sort_values("Date", kind="stable")
                sign = ledger_frame["Treatment"].map({"Loan receivable": 1, "Principal repayment": 1,
                                                      "Receivable repayment": -1, "Loan draw": -1})
                ledger_frame["Running balance"] = (sign * ledger_frame["Amount"]).cumsum().round(2)
                ledger_frame = ledger_frame.iloc[::-1]
                st.caption("Running balance: positive means they owe us, negative means we owe them. "
                           "Read it from the bottom (oldest) to see where it goes wrong.")
            ledger_frame = ledger_frame[["Date", "From", "To", "Amount", "What happened", "Notes", "Account", "Description",
                                         "Source"] + (["Running balance"] if "Running balance" in ledger_frame else [])]
            st.caption("Click a Notes cell to write why the loan was given or taken, then press Save notes.")
            edited_ledger = st.data_editor(
                ledger_frame, hide_index=True, width="stretch", key=f"loan_ledger_editor_{party_pick}",
                disabled=[c for c in ledger_frame.columns if c != "Notes"],
                column_config={"Notes": st.column_config.TextColumn("Notes (why)", width="large",
                                                                    help="For example: working capital for payroll"),
                               "Amount": st.column_config.NumberColumn(format="$%.2f"),
                                        "Running balance": st.column_config.NumberColumn(format="$%.2f"),
                                        "Date": st.column_config.TextColumn(width="small"),
                                        "From": st.column_config.TextColumn(width="medium"),
                                        "To": st.column_config.TextColumn(width="medium"),
                                        "Description": st.column_config.TextColumn(width="large")})
            changed_notes = [{"kind": key.split(":")[0], "id": key.split(":")[1], "notes": row["Notes"]}
                             for key, row in edited_ledger.iterrows()
                             if (row["Notes"] or "").strip() != (ledger_frame.loc[key, "Notes"] or "").strip()]
            if st.button(f"Save {len(changed_notes)} note(s)", type="primary", disabled=not changed_notes,
                         key="save_loan_notes"):
                with db.connect(DB_PATH) as connection:
                    db.set_loan_notes(connection, business_id, changed_notes)
                st.success("Notes saved.")
                rerun()
            csv_download("Download loan transactions (CSV)", edited_ledger, "loan-transactions", "dl_loan_ledger")

    with tab_excluded:
        include_unreviewed = st.checkbox("Also list transactions not yet classified", key="excluded_unreviewed")
        with db.connect(DB_PATH) as connection:
            excluded_rows = db.excluded_from_pnl(connection, business_id, r_start, r_end, include_unreviewed)
        if not excluded_rows:
            st.info("Nothing is excluded in this period.")
        else:
            excluded_frame = pd.DataFrame(excluded_rows)
            by_reason = excluded_frame.groupby("reason", as_index=False).agg(
                Transactions=("id", "count"), Money_in=("signed_amount", lambda x: x[x > 0].sum()),
                Money_out=("signed_amount", lambda x: -x[x < 0].sum())).rename(
                columns={"reason": "Reason", "Money_in": "Money in", "Money_out": "Money out"})
            section_label("Excluded by reason")
            st.dataframe(by_reason, hide_index=True, width="stretch", column_config={
                "Money in": st.column_config.NumberColumn(format="$%.2f"),
                "Money out": st.column_config.NumberColumn(format="$%.2f")})
            reasons = st.multiselect("Reason", sorted(excluded_frame["reason"].unique()), placeholder="All reasons",
                                     key="excluded_reason_filter")
            search = st.text_input("Search", key="excluded_search", placeholder="Description, party, account…")
            detail = excluded_frame.copy()
            if reasons:
                detail = detail[detail["reason"].isin(reasons)]
            if search.strip():
                hay = detail[["description", "counterparty", "account", "notes"]].fillna("").agg(" ".join, axis=1).str.lower()
                detail = detail[hay.str.contains(search.strip().lower(), regex=False)]
            detail = detail.rename(columns={
                "id": "Transaction #", "date": "Date", "account": "Account", "description": "Description",
                "signed_amount": "Amount", "treatment": "Treatment", "counterparty": "Party", "category": "Category",
                "reason": "Reason", "notes": "Notes"})[
                ["Transaction #", "Date", "Account", "Description", "Amount", "Reason", "Treatment", "Party", "Category", "Notes"]]
            section_label(f"{len(detail):,} excluded transactions")
            st.dataframe(detail, hide_index=True, width="stretch",
                         column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
            csv_download("Download excluded list (CSV)", detail, "excluded-from-pnl", "dl_excluded")

    with tab_vendor:
        if not vendor_rows:
            st.info("No revenue or expense in this period.")
        else:
            v1, v2 = st.columns([2, 1.2])
            vendor_search = v1.text_input("Search vendor / party", key="vendor_report_search")
            vendor_view = v2.selectbox("Show", ["All", "Revenue only", "Expense only"], key="vendor_report_view")
            vendor_frame = pd.DataFrame(vendor_rows).rename(columns={
                "party": "Vendor / party", "revenue": "Revenue", "expense": "Expense", "net": "Net",
                "transactions": "Transactions", "last_activity": "Last activity"})
            if vendor_search.strip():
                vendor_frame = vendor_frame[vendor_frame["Vendor / party"].str.lower().str.contains(
                    vendor_search.strip().lower(), regex=False)]
            if vendor_view == "Revenue only":
                vendor_frame = vendor_frame[vendor_frame["Revenue"] != 0]
            elif vendor_view == "Expense only":
                vendor_frame = vendor_frame[vendor_frame["Expense"] != 0]
            m1, m2, m3 = st.columns(3)
            with m1: metric_card("Revenue", money(float(vendor_frame["Revenue"].sum())), "Shown below", "↗", "teal")
            with m2: metric_card("Expenses", money(float(vendor_frame["Expense"].sum())), "Shown below", "↘", "rose")
            with m3: metric_card("Net", money(float(vendor_frame["Net"].sum())), "Revenue less expenses", "◆", "navy")
            st.dataframe(vendor_frame, hide_index=True, width="stretch", column_config={
                c: st.column_config.NumberColumn(format="$%.2f") for c in ("Revenue", "Expense", "Net")})
            st.caption("The vendor is the party on the transaction, else the bank-text rule (Parties page) that matches it. "
                       "Loans, transfers and owner contributions are not included.")
            csv_download("Download vendor report (CSV)", vendor_frame, "revenue-expense-by-vendor", "dl_vendor_report")

    with tab_margin:
        with db.connect(DB_PATH) as connection:
            margin = db.margin_report(connection, business_id, r_start, r_end)
            links = db.list_margin_links(connection, business_id)
            all_party_names = [p["party"] for p in db.list_parties(connection, business_id)]
        customers = margin["customers"]
        total_rev = sum(c["revenue"] for c in customers)
        total_exp = sum(c["mapped_expense"] for c in customers)
        total_margin = total_rev - total_exp
        k1, k2, k3, k4 = st.columns(4)
        with k1: metric_card("Revenue", money(total_rev), "From revenue companies", "↗", "teal")
        with k2: metric_card("Mapped expense", money(total_exp), "Paid to their mapped companies", "↘", "rose")
        with k3: metric_card("Margin", money(total_margin), "Revenue less mapped expense", "◆", "navy")
        with k4: metric_card("Margin %", f"{total_margin / total_rev * 100:.1f}%" if total_rev else "—", "Of revenue", "%", "gold")

        section_label("Margin by revenue company")
        if customers:
            margin_frame = pd.DataFrame([{
                "Revenue company": c["customer"], "Revenue": c["revenue"], "Mapped expense": c["mapped_expense"],
                "Margin": c["margin"], "Margin %": c["margin_pct"],
                "Expense companies": c["expense_companies"] or "⚠ none mapped yet"} for c in customers])
            st.dataframe(margin_frame, hide_index=True, width="stretch", column_config={
                "Revenue": st.column_config.NumberColumn(format="$%.2f"),
                "Mapped expense": st.column_config.NumberColumn(format="$%.2f"),
                "Margin": st.column_config.NumberColumn(format="$%.2f"),
                "Margin %": st.column_config.NumberColumn(format="%.1f%%")})
            csv_download("Download margin report (CSV)", margin_frame, "margin-by-company", "dl_margin")
            pick = st.selectbox("See which expense companies make up a margin",
                                [c["customer"] for c in customers if margin["details"].get(c["customer"])] or ["—"],
                                key="margin_detail_pick")
            if margin["details"].get(pick):
                st.dataframe(pd.DataFrame(margin["details"][pick]).rename(
                    columns={"expense_party": "Expense company", "expense": "Expense in period"}),
                    hide_index=True, width="stretch",
                    column_config={"Expense in period": st.column_config.NumberColumn(format="$%.2f")})
        else:
            st.info("No revenue in this period yet.")

        section_label("Map expense companies to a revenue company")
        st.caption("Each expense company belongs to one revenue company. Choose the revenue company, tick the companies "
                   "you pay to serve it, and save. Margin is revenue less what you paid those companies.")
        link_of = {db._payee_key(l["expense_party"]): l["revenue_party"] for l in links}
        revenue_options = sorted({c["customer"] for c in customers} | {l["revenue_party"] for l in links}
                                 | {p for p in all_party_names}, key=str.lower)
        expense_pool = sorted({v["party"] for v in vendor_rows if v["expense"] > 0} | {l["expense_party"] for l in links},
                              key=lambda n: (db._payee_key(n) in link_of, n.lower()))
        with st.form("margin_link_form", clear_on_submit=True):
            revenue_company = st.selectbox("Revenue company", ["— choose —"] + revenue_options, key="margin_revenue_company")
            expense_companies = st.multiselect(
                "Expense companies serving it", expense_pool, key="margin_expense_companies",
                format_func=lambda n: n + (f"  → now mapped to {link_of[db._payee_key(n)]}" if db._payee_key(n) in link_of else ""))
            if st.form_submit_button("Save mapping", type="primary", width="stretch"):
                try:
                    with db.connect(DB_PATH) as connection:
                        count = db.set_margin_links(
                            connection, business_id=business_id,
                            revenue_party="" if revenue_company.startswith("—") else revenue_company,
                            expense_parties=expense_companies)
                    st.session_state["margin_message"] = f"Mapped {count} expense company(ies) to {revenue_company}."
                    rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if st.session_state.get("margin_message"):
            st.success(st.session_state.pop("margin_message"))

        if links:
            section_label("Current mappings")
            link_frame = pd.DataFrame(links).rename(columns={"revenue_party": "Revenue company", "expense_party": "Expense company"})
            link_grid = st.dataframe(link_frame[["Revenue company", "Expense company"]], hide_index=True, width="stretch",
                                     key=f"margin_link_grid_{len(links)}", on_select="rerun", selection_mode="multi-row")
            chosen_links = [links[i]["id"] for i in link_grid.selection.rows]
            if st.button(f"Remove {len(chosen_links)} selected mapping(s)", disabled=not chosen_links, key="margin_remove"):
                with db.connect(DB_PATH) as connection:
                    db.delete_margin_links(connection, business_id, chosen_links)
                rerun()
        if margin["unmapped_expenses"]:
            section_label("Expense companies not yet mapped")
            st.dataframe(pd.DataFrame(margin["unmapped_expenses"]).rename(columns={
                "party": "Expense company", "expense": "Expense in period", "transactions": "Transactions"}),
                hide_index=True, width="stretch",
                column_config={"Expense in period": st.column_config.NumberColumn(format="$%.2f")})


elif page == "Staff & Payroll":
    month_options = staff_mod.recent_months(30)
    default_month = date.today().strftime("%Y-%m")
    month_col, _ = st.columns([1, 3])
    st.session_state.setdefault("staff_month", default_month if default_month in month_options else month_options[0])
    month = month_col.selectbox("Month", month_options, key="staff_month")
    page_header("Staff paid and company revenue",
                "Enter what you paid each staff member or staff company by month. Pick the deposits that are revenue from a company and see the total.",
                "Staff & payroll")
    tab_paid, tab_rev, tab_sum = st.tabs(["Staff paid", "Revenue from a company", "Monthly summary"])

    with tab_paid:
        with db.connect(DB_PATH) as connection:
            staff_names = [p["name"] for p in staff_mod.list_staff(connection, business_id)]
            payments = staff_mod.list_payments(connection, business_id, month)
            suggestions = staff_mod.payment_suggestions(connection, business_id, month)
            category_names = [c["name"] for c in db.list_categories(connection, business_id)]
        previous = staff_mod.previous_month(month)
        n1, n2, n3, _ = st.columns([2.2, 1, 1, 3])
        if n1.button(f"Auto-fill {month} from {previous}", key="staff_autofill",
                     help=f"Looks up each person paid in {previous} and adds their bank payments found in {month}."):
            with db.connect(DB_PATH) as connection:
                result = staff_mod.autofill_payments(connection, business_id, month)
            if not result["people"]:
                st.info(f"Nobody was entered for {previous}, so there is nothing to fill from.")
            else:
                st.success(f"Added {result['added']} payment{'s' if result['added'] != 1 else ''} found in {month}."
                           + (f" No bank payment found yet for: {', '.join(result['no_match'])}." if result["no_match"] else ""))
        n2.button("← Previous", key="staff_prev_month", on_click=shift_staff_month, args=(-1,))
        n3.button("Next month →", key="staff_next_month", on_click=shift_staff_month, args=(1,), type="primary")
        who_list = st.multiselect("Staff or company (pick several to search them all)", staff_names, accept_new_options=True,
                                  key="staff_who", placeholder="Pick or type names")
        if who_list:
            name_found, seen = [], set()
            with db.connect(DB_PATH) as connection:
                for person in who_list:
                    for t in staff_mod.name_matches(connection, business_id, person, month):
                        if t["id"] not in seen:
                            seen.add(t["id"])
                            name_found.append({**t, "who": person})
            if name_found:
                st.caption(f"Bank payments in {month} that mention the names you picked. Untick any that are not theirs, then add them.")
                found_frame = pd.DataFrame([{
                    "id": t["id"], "Add": True, "Staff": t["who"], "Date": t["transaction_date"],
                    "Amount": abs(t["signed_amount"]), "Description": t["description"], "Memo / note": t["memo"],
                    "Category": t["category"] or ""} for t in name_found])
                found_edit = st.data_editor(
                    found_frame, hide_index=True, width="stretch", key=f"staff_found_{'|'.join(who_list)}_{month}",
                    column_order=["Add", "Staff", "Date", "Amount", "Description", "Memo / note", "Category"],
                    disabled=["Staff", "Date", "Amount", "Description", "Memo / note", "Category"],
                    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
                picked = found_edit[found_edit["Add"]]
                if st.button(f"Add {len(picked)} payment{'s' if len(picked) != 1 else ''} ({money(float(picked['Amount'].sum()))}) for {month}",
                             type="primary", key="staff_add_found", disabled=picked.empty):
                    try:
                        with db.connect(DB_PATH) as connection:
                            for person in who_list:
                                ids = [int(r["id"]) for _, r in picked.iterrows() if r["Staff"] == person]
                                if ids:
                                    staff_mod.add_payments_from_transactions(connection, business_id, name=person, month=month,
                                                                             transaction_ids=ids)
                        rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.caption(f"No unmatched bank payments in {month} mention those names. Enter an amount below for one name.")
        with st.form("add_staff_payment", clear_on_submit=True):
            f2, f3, f4 = st.columns([1, 2, 1])
            amount = f2.number_input("Amount paid", min_value=0.0, step=1.0, format="%.2f")
            note = f3.text_input("Note (optional)", placeholder="Check number, hours, invoice…")
            f4.write("")
            if f4.form_submit_button(f"Add payment for {month}", type="primary"):
                if len(who_list) != 1:
                    st.error("Pick exactly one name to add an amount by hand.")
                else:
                    try:
                        with db.connect(DB_PATH) as connection:
                            staff_mod.add_payment(connection, business_id, name=who_list[0], month=month, amount=amount, note=note)
                        rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        total_paid = round(sum(p["amount"] for p in payments), 2)
        st.metric(f"Total paid in {month}", money(total_paid))
        if payments:
            st.dataframe(pd.DataFrame([{
                "Staff or company": p["staff"], "Amount": p["amount"], "Note": p["note"],
                "Bank payment": (f"{p['bank_date']} · {p['bank_description'][:50]}" if p["transaction_id"] else "Not matched")}
                for p in payments]), hide_index=True, width="stretch",
                column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
            per_person: dict[str, float] = {}
            for p in payments:
                per_person[p["staff"]] = round(per_person.get(p["staff"], 0.0) + p["amount"], 2)
            if len(per_person) != len(payments):
                with st.expander("Totals by person"):
                    st.dataframe(pd.DataFrame([{"Staff or company": k, "Total": v} for k, v in per_person.items()]),
                                 hide_index=True, width="stretch",
                                 column_config={"Total": st.column_config.NumberColumn(format="$%.2f")})
            r1, r2 = st.columns([3, 1])
            remove = r1.selectbox("Remove a payment", [p["id"] for p in payments], index=None, placeholder="Choose a payment…",
                                  format_func=lambda pid: next(f"{p['staff']} · {money(p['amount'])}" for p in payments if p["id"] == pid),
                                  key="staff_remove")
            if remove and r2.button("Remove", key="staff_remove_go"):
                with db.connect(DB_PATH) as connection:
                    staff_mod.delete_payment(connection, business_id, int(remove))
                rerun()
        else:
            st.info(f"Nothing entered for {month} yet.")
        if payments:
            k1, k2 = st.columns([3, 1])
            copy_target = k1.selectbox("Copy this month's payments to", [m for m in month_options if m != month], index=None,
                                       placeholder="Choose a month…", key="staff_copy_target",
                                       help="Copies names, amounts and notes. Bank links are not copied.")
            if copy_target and k2.button("Copy", key="staff_copy_go"):
                try:
                    with db.connect(DB_PATH) as connection:
                        copied = staff_mod.copy_payments(connection, business_id, month, copy_target)
                    st.success(f"Copied {copied} payment{'s' if copied != 1 else ''} to {copy_target}."
                               + ("" if copied else " They were already there."))
                except ValueError as exc:
                    st.error(str(exc))
        if suggestions:
            section_label("Match to bank payments")
            default_cat = "Payroll"
            file_options = ["Don't change the transaction"] + category_names + ([default_cat] if default_cat not in category_names else [])
            file_choice = st.selectbox("When I link one, file the bank transaction under", file_options, key="staff_file_cat",
                                       help="Choose a category to also set the transaction's category to it, mark it as an expense and name the payee.")
            for number, s in enumerate(suggestions[:15]):
                txn, pay = s["transaction"], s["payment"]
                c1, c2 = st.columns([5, 1])
                c1.write(f"**{pay['staff']}** {money(pay['amount'])} ↔ {txn['transaction_date']} · {money(abs(txn['signed_amount']))} · "
                         f"{txn['description'][:60]} _({s['why']})_")
                if c2.button("Link", key=f"staff_link_{pay['id']}_{txn['id']}_{number}"):
                    try:
                        with db.connect(DB_PATH) as connection:
                            cat_id = None if file_choice == file_options[0] else db.get_or_create_category(
                                connection, business_id, file_choice, "Expense")
                            staff_mod.link_payment(connection, business_id, pay["id"], txn["id"], category_id=cat_id)
                        rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        linked = [p for p in payments if p["transaction_id"]]
        if linked:
            unlink = st.selectbox("Unlink a bank payment", [p["id"] for p in linked], index=None, placeholder="Choose…",
                                  format_func=lambda pid: next(f"{p['staff']} · {money(p['amount'])}" for p in linked if p["id"] == pid),
                                  key="staff_unlink")
            if unlink and st.button("Unlink", key="staff_unlink_go"):
                with db.connect(DB_PATH) as connection:
                    staff_mod.unlink_payment(connection, business_id, int(unlink))
                rerun()

    with tab_rev:
        with db.connect(DB_PATH) as connection:
            company_options = sorted(set(db.known_parties(connection, business_id)) | set(staff_mod.picked_companies(connection, business_id)),
                                     key=str.lower)
        start_default, end_default = staff_mod.month_range(month)
        q1, q2, q3 = st.columns([2, 1, 1])
        companies = q1.multiselect("Companies (pick several)", company_options, accept_new_options=True, key="staff_company",
                                   placeholder="Pick, or type text that appears in the bank memo")
        from_date = q2.date_input("From", value=date.fromisoformat(start_default), key=f"staff_from_{month}")
        to_date = q3.date_input("To", value=date.fromisoformat(end_default), key=f"staff_to_{month}")
        v1, v2, v3, _ = st.columns([2.2, 1, 1, 3])
        if v1.button(f"Auto-fill {month} from {staff_mod.previous_month(month)}", key="staff_rev_autofill",
                     help="Picks this month's deposits for every company you picked last month."):
            with db.connect(DB_PATH) as connection:
                result = staff_mod.autofill_revenue(connection, business_id, month)
            if not result["companies"]:
                st.info(f"No revenue was picked for {staff_mod.previous_month(month)}, so there is nothing to fill from.")
            else:
                st.success(f"Picked {result['added']} deposit{'s' if result['added'] != 1 else ''} for {month}."
                           + (f" Nothing found yet for: {', '.join(result['no_match'])}." if result["no_match"] else ""))
        v2.button("← Previous", key="staff_rev_prev_month", on_click=shift_staff_month, args=(-1,))
        v3.button("Next month →", key="staff_rev_next_month", on_click=shift_staff_month, args=(1,), type="primary")
        st.caption("Deposits whose description, name or check payee contains the company. Tick the ones that are revenue from it.")
        if companies:
            found, seen = [], set()
            with db.connect(DB_PATH) as connection:
                for company in companies:
                    for t in staff_mod.revenue_candidates(connection, business_id, company, from_date.isoformat(), to_date.isoformat()):
                        if t["id"] not in seen:
                            seen.add(t["id"])
                            found.append({**t, "company": company})
            if not found:
                st.info("No deposits found for those companies in this period. Widen the dates or try a shorter piece of the name.")
            else:
                pick_frame = pd.DataFrame([{
                    "id": t["id"], "Include": True, "Company": t["company"], "Date": t["transaction_date"],
                    "Amount": t["signed_amount"], "Description": t["description"], "Memo / note": t["memo"],
                    "Category": t["category"] or "", "Treatment": t["treatment"]} for t in found])
                edited = st.data_editor(
                    pick_frame, hide_index=True, width="stretch",
                    key=f"staff_rev_{'|'.join(companies)}_{from_date}_{to_date}",
                    column_order=["Include", "Company", "Date", "Amount", "Description", "Memo / note", "Category", "Treatment"],
                    disabled=["Company", "Date", "Amount", "Description", "Memo / note", "Category", "Treatment"],
                    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
                chosen = edited[edited["Include"]]
                t1, t2 = st.columns(2)
                t1.metric("Revenue picked", money(float(chosen["Amount"].sum())))
                t2.metric("Deposits", f"{len(chosen)} of {len(edited)}")
                if len(companies) > 1:
                    st.dataframe(chosen.groupby("Company", as_index=False)["Amount"].sum().rename(columns={"Amount": "Total"}),
                                 hide_index=True, width="stretch",
                                 column_config={"Total": st.column_config.NumberColumn(format="$%.2f")})
                if st.button("Save picks", type="primary", key="staff_rev_save"):
                    with db.connect(DB_PATH) as connection:
                        for company in companies:
                            shown = [int(r["id"]) for _, r in edited.iterrows() if r["Company"] == company]
                            keep = [int(r["id"]) for _, r in chosen.iterrows() if r["Company"] == company]
                            if shown:
                                staff_mod.save_revenue_picks(connection, business_id, company, shown, keep)
                    st.success("Saved. These now show in the Monthly summary.")
        with db.connect(DB_PATH) as connection:
            saved = staff_mod.revenue_by_month(connection, business_id)
        if saved:
            section_label("Saved revenue by company and month")
            st.dataframe(pd.DataFrame([{"Month": r["month"], "Company": r["company"], "Deposits": r["deposits"],
                                        "Revenue": r["total"]} for r in saved]), hide_index=True, width="stretch",
                         column_config={"Revenue": st.column_config.NumberColumn(format="$%.2f")})

    with tab_sum:
        ascending = sorted(month_options)
        end_default = month if month in ascending else ascending[-1]
        start_index = max(ascending.index(end_default) - 5, 0)
        sm1, sm2, sm3 = st.columns([1, 1, 1.4])
        sum_from = sm1.selectbox("From month", ascending, index=start_index, key="staff_sum_from")
        sum_to = sm2.selectbox("To month", ascending, index=ascending.index(end_default), key="staff_sum_to")
        show_what = sm3.radio("Show", ["Both", "Staff paid", "Revenue"], horizontal=True, key="staff_sum_show")
        if sum_from > sum_to:
            st.warning("The From month is after the To month.")
        else:
            with db.connect(DB_PATH) as connection:
                all_paid = staff_mod.paid_detail(connection, business_id, sum_from, sum_to)
                all_revenue = staff_mod.revenue_detail(connection, business_id, sum_from, sum_to)
            f1, f2 = st.columns(2)
            staff_pick = f1.multiselect("Staff (empty = everyone)", sorted({r["name"] for r in all_paid}, key=str.lower),
                                        key="staff_sum_staff", disabled=show_what == "Revenue")
            company_pick = f2.multiselect("Revenue companies (empty = all)", sorted({r["name"] for r in all_revenue}, key=str.lower),
                                          key="staff_sum_companies", disabled=show_what == "Staff paid")
            paid_rows = [r for r in all_paid if show_what != "Revenue" and (not staff_pick or r["name"] in staff_pick)]
            revenue_rows = [r for r in all_revenue if show_what != "Staff paid" and (not company_pick or r["name"] in company_pick)]
            months_list = staff_mod.months_between(sum_from, sum_to)
            by_month = pd.DataFrame({"Month": months_list})
            by_month["Paid to staff"] = by_month["Month"].map(
                lambda m: round(sum(r["total"] for r in paid_rows if r["month"] == m), 2))
            by_month["Revenue"] = by_month["Month"].map(
                lambda m: round(sum(r["total"] for r in revenue_rows if r["month"] == m), 2))
            by_month["Margin"] = (by_month["Revenue"] - by_month["Paid to staff"]).round(2)
            totals_paid, totals_revenue = by_month["Paid to staff"].sum(), by_month["Revenue"].sum()
            k1, k2, k3 = st.columns(3)
            k1.metric("Paid to staff", money(float(totals_paid)))
            k2.metric("Revenue", money(float(totals_revenue)))
            k3.metric("Margin", money(float(totals_revenue - totals_paid)))
            shown_columns = {"Both": ["Month", "Paid to staff", "Revenue", "Margin"],
                             "Staff paid": ["Month", "Paid to staff"], "Revenue": ["Month", "Revenue"]}[show_what]
            money_config = {c: st.column_config.NumberColumn(format="$%.2f") for c in ("Paid to staff", "Revenue", "Margin")}
            st.dataframe(by_month[shown_columns], hide_index=True, width="stretch", column_config=money_config)

            def pivot(rows: list[dict], label: str) -> pd.DataFrame:
                table = pd.DataFrame(rows).pivot_table(index="name", columns="month", values="total", aggfunc="sum",
                                                       fill_value=0.0).reindex(columns=months_list, fill_value=0.0)
                table["Total"] = table.sum(axis=1)
                table.loc["All"] = table.sum()
                table.index.name = label
                return table.reset_index()

            for rows, label in ((paid_rows, "Staff or company"), (revenue_rows, "Revenue company")):
                if rows:
                    section_label("Paid to " + "each person" if label.startswith("Staff") else "Revenue by company")
                    table = pivot(rows, label)
                    st.dataframe(table, hide_index=True, width="stretch",
                                 column_config={c: st.column_config.NumberColumn(format="$%.2f") for c in table.columns if c != label})
                    csv_download("Download CSV", table, f"{'staff-paid' if label.startswith('Staff') else 'revenue'}-{sum_from}-to-{sum_to}",
                                 key=f"staff_sum_csv_{label}")
            if not paid_rows and not revenue_rows:
                st.info("Nothing in this period for the selection.")
            st.caption("Revenue counts only the deposits you picked and saved. Paid to staff is the amounts you entered.")

elif page == "Parties":
    page_header("Everyone you do business with",
                "Lenders, borrowers, customers and payees in one list. Rename a party everywhere or merge duplicate spellings.",
                "Parties")
    party_view = st.radio("View", ["Parties", "Bank-text rules"], horizontal=True, key="party_view",
                          label_visibility="collapsed",
                          help="Bank-text rules were the separate Vendors page: they file transactions under a party automatically.")
    if party_view == "Bank-text rules":
        render_bank_text_rules()
        st.stop()
    with db.connect(DB_PATH) as connection:
        parties = db.list_parties(connection, business_id)
        rule_keys: dict[str, int] = {}
        for rule in db.list_vendors(connection, business_id):
            key = db._payee_key(rule["name"], loose=True)
            rule_keys[key] = rule_keys.get(key, 0) + 1
    if not parties:
        st.info("No parties yet. Names appear here once you add a counterparty to a transaction or confirm a check.")
        st.stop()
    p1, p2, p3 = st.columns([2, 1.2, 1])
    party_search = p1.text_input("Search parties", key="party_search", placeholder="Name…")
    party_kind = p2.selectbox("Show", ["All parties", "Owe us money", "We owe them", "Several spellings"], key="party_kind")
    needle = party_search.strip().lower()
    shown = [p for p in parties
             if (not needle or needle in " ".join(p["spellings"]).lower())
             and (party_kind == "All parties"
                  or (party_kind == "Owe us money" and abs(p["owed_to_us"]) > 0.004)
                  or (party_kind == "We owe them" and abs(p["we_owe"]) > 0.004)
                  or (party_kind == "Several spellings" and len(p["spellings"]) > 1))]
    p3.metric("Parties", f"{len(shown):,} of {len(parties):,}")
    if not shown:
        st.info("No parties match these filters.")
        st.stop()
    party_frame = pd.DataFrame([{
        "Party": p["party"], "Spellings on record": " · ".join(p["spellings"]) if len(p["spellings"]) > 1 else "",
        "Transactions": p["transactions"], "Checks": p["checks"], "Money in": p["money_in"],
        "Money out": p["money_out"], "Owes us": p["owed_to_us"], "We owe": p["we_owe"],
        "Bank-text rules": rule_keys.get(db._payee_key(p["party"], loose=True), 0),
        "Last activity": p["last_activity"]} for p in shown])
    st.caption("Select one or more rows, then rename or merge below.")
    money_cols = {c: st.column_config.NumberColumn(format="$%.2f") for c in ("Money in", "Money out", "Owes us", "We owe")}
    party_grid = st.dataframe(party_frame, hide_index=True, width="stretch", key=f"party_grid_{needle}_{party_kind}",
                              on_select="rerun", selection_mode="multi-row", column_config=money_cols)
    picked = [shown[i] for i in party_grid.selection.rows]
    if picked:
        names = [n for p in picked for n in p["spellings"]]
        with st.container(border=True):
            st.markdown(f"**{len(picked)} selected** · " + ", ".join(p["party"] for p in picked[:4]) + ("…" if len(picked) > 4 else ""))
            default_name = max(names, key=len)
            new_name = st.text_input(
                "Rename to" if len(picked) == 1 and len(names) == 1 else "Rename / merge into",
                value=default_name, key=f"party_new_{'|'.join(sorted(names))}",
                help="Every selected spelling is changed to this name on transactions and checks.")

            @st.dialog("Rename or merge parties?")
            def confirm_party_dialog(old_names: list[str], target: str) -> None:
                st.write(f"Change **{len(old_names)}** spelling(s) to **{target}**:")
                st.caption(" · ".join(old_names))
                st.caption("Applies to bank transactions, the check register and the statement log. Amounts are never changed.")
                yes, no = st.columns(2)
                if yes.button("Apply", type="primary", width="stretch"):
                    with db.connect(DB_PATH) as connection:
                        counts = db.rename_party(connection, business_id=business_id, old_names=old_names, new_name=target)
                    st.session_state["party_message"] = (
                        f"Renamed to {target}: {counts['transactions']} transaction(s), {counts['checks']} check(s) updated.")
                    rerun()
                if no.button("Cancel", width="stretch"):
                    st.rerun()

            changes = [n for n in names if n != " ".join(new_name.split())] or names
            if st.button("Rename / merge…", type="primary", disabled=not new_name.strip()
                         or (len(names) == 1 and names[0] == " ".join(new_name.split()))):
                confirm_party_dialog(changes, new_name)
        if len(picked) == 1:
            with db.connect(DB_PATH) as connection:
                activity = db.party_activity(connection, business_id, names)
            section_label(f"Activity for {picked[0]['party']}")
            if activity["transactions"]:
                st.markdown("**Bank transactions**")
                st.dataframe(pd.DataFrame(activity["transactions"]).rename(columns={
                    "id": "Transaction #", "transaction_date": "Date", "account": "Account", "description": "Description",
                    "signed_amount": "Amount", "treatment": "Treatment"}), hide_index=True, width="stretch",
                    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
            if activity["checks"]:
                st.markdown("**Checks**")
                st.dataframe(pd.DataFrame(activity["checks"]).rename(columns={
                    "cleared_date": "Cleared", "check_number": "Check #", "check_type": "Direction", "amount": "Amount",
                    "account": "Account", "treatment": "Treatment", "memo": "Memo"}), hide_index=True, width="stretch",
                    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
    if st.session_state.get("party_message"):
        st.success(st.session_state.pop("party_message"))


elif page == "Categories & Rules":
    page_header("Your accounting vocabulary",
                "Categories and rules belong to the business you have selected. Learned rules handle repeat descriptions, and you can edit or clean them up. To copy a setup to another business, use Admin & backup.",
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
            with db.connect(DB_PATH) as connection:
                clutter = db.rule_cleanup_candidates(connection, business_id)
            if clutter:
                with st.expander(f"Clean up: {len(clutter)} rule(s) that are probably clutter"):
                    st.caption("One-off check-number rules, loan rules on generic bank text, and switched-off unused rules. "
                               "Deleting a rule never changes transactions it already classified. "
                               "Bank-text rules on the Parties page are not listed here.")
                    clutter_frame = pd.DataFrame([{
                        "Delete": True, "Why": c["reason"], "Phrase": c["pattern"], "Account": c["account_name"] or "All accounts",
                        "Treatment": c["treatment"], "Category": c["category_name"] or ""} for c in clutter])
                    clutter_frame.index = [c["id"] for c in clutter]
                    picked_clutter = st.data_editor(clutter_frame, key="rule_cleanup_editor", width="stretch",
                                                    disabled=["Why", "Phrase", "Account", "Treatment", "Category"])
                    to_delete = [int(i) for i, r in picked_clutter.iterrows() if r["Delete"]]
                    if st.button(f"Delete {len(to_delete)} ticked rule(s)", type="primary", disabled=not to_delete,
                                 key="rule_cleanup_apply"):
                        with db.connect(DB_PATH) as connection:
                            removed = db.delete_rules(connection, business_id, to_delete)
                        st.success(f"Deleted {removed} rule(s).")
                        rerun()
            f1, f2, f3 = st.columns([2, 1.3, 1])
            rule_search = f1.text_input("Search rules", key="rule_search", placeholder="Phrase or category…")
            rule_treatment = f2.selectbox("Treatment", ["All"] + list(db.TREATMENTS[:-1]), key="rule_treatment_filter")
            rule_state = f3.selectbox("Show", ["All", "Active", "Off"], key="rule_state_filter")
            needle = rule_search.strip().lower()
            rules = [r for r in rules
                     if (not needle or needle in r["pattern"].lower() or needle in (r["category_name"] or "").lower())
                     and (rule_treatment == "All" or r["treatment"] == rule_treatment)
                     and (rule_state == "All" or bool(r["active"]) == (rule_state == "Active"))]
            st.caption(f"{len(rules):,} rule(s) shown")
            if not rules:
                st.info("No rules match these filters.")
                st.stop()
            st.dataframe(pd.DataFrame(rules)[["id", "pattern", "account_name", "category_name", "treatment", "hit_count", "active"]],
                         hide_index=True, width="stretch")
            rule_ids = {f"#{item['id']} · {item['pattern'][:70]}{' · off' if not item['active'] else ''}": item for item in rules}
            chosen = st.selectbox("Rule to edit", list(rule_ids))
            rule = rule_ids[chosen]
            with db.connect(DB_PATH) as connection:
                rule_categories = db.list_categories(connection, business_id)
                rule_accounts = db.list_accounts(connection, business_id)
            cat_names = ["(none)"] + [c["name"] for c in rule_categories]
            cat_now = rule["category_name"] if rule["category_name"] in cat_names else "(none)"
            acct_names = ["(none)"] + [a["name"] for a in rule_accounts]
            acct_now = rule["related_account_name"] if rule["related_account_name"] in acct_names else "(none)"
            treatments = list(db.TREATMENTS[:-1])
            st.caption(f"Applies to: {rule['account_name'] or 'all accounts'} · matched {rule['hit_count']} transaction(s)")
            with st.form(f"edit_rule_{rule['id']}"):
                e_pattern = st.text_input("Description contains", value=rule["pattern"])
                e1, e2 = st.columns(2)
                e_category = e1.selectbox("Category", cat_names, index=cat_names.index(cat_now))
                e_treatment = e2.selectbox("Treatment", treatments,
                                           index=treatments.index(rule["treatment"]) if rule["treatment"] in treatments else 0)
                e3, e4 = st.columns(2)
                e_related = e3.selectbox("Related account (transfers)", acct_names, index=acct_names.index(acct_now))
                e_priority = e4.number_input("Priority (higher wins)", value=int(rule["priority"]), step=10)
                e_active = st.checkbox("Active", value=bool(rule["active"]))
                e_apply = st.checkbox("Apply to transactions still waiting for review", value=False)
                if st.form_submit_button("Save rule changes", type="primary", width="stretch"):
                    try:
                        with db.connect(DB_PATH) as connection:
                            applied = db.update_rule(
                                connection, int(rule["id"]), pattern=e_pattern,
                                category_id=next((c["id"] for c in rule_categories if c["name"] == e_category), None),
                                treatment=e_treatment,
                                related_account_id=next((a["id"] for a in rule_accounts if a["name"] == e_related), None),
                                priority=int(e_priority), active=e_active, apply_existing=e_apply)
                        st.success(f"Rule updated. {applied} waiting transaction(s) classified.")
                        rerun()
                    except Exception as exc:
                        st.error(str(exc))
            confirm_delete = st.checkbox("I want to delete this rule", key=f"confirm_rule_delete_{rule['id']}")
            if st.button("Delete rule", disabled=not confirm_delete, key=f"delete_rule_{rule['id']}"):
                with db.connect(DB_PATH) as connection:
                    db.delete_rule(connection, int(rule["id"]))
                st.success("Rule deleted. Transactions it classified keep their classification.")
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
