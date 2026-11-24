"""Sign-in screens: first-time owner setup, login with authenticator code, MFA enrolment, recovery codes."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import streamlit as st

from . import access, auth, db

INACTIVITY_SECONDS = int(os.getenv("SESSION_MINUTES", "30")) * 60
AUTH_OFF = os.getenv("BOOKS_AUTH", "") == "off"  # development and tests only


def _centered():
    _, middle, _ = st.columns([1, 1.3, 1])
    return middle


def _sign_in(db_path: Path, username: str, how: str = "") -> None:
    with db.connect(db_path) as connection:
        access.log(connection, username, "sign in", how)
    st.session_state["auth_user"] = username
    st.session_state["auth_seen"] = time.time()
    for key in ("auth_enroll", "enroll_secret", "auth_codes", "auth_notice"):
        st.session_state.pop(key, None)
    st.rerun()


def sign_out(db_path: Path, reason: str = "") -> None:
    username = st.session_state.get("auth_user")
    if username:
        with db.connect(db_path) as connection:
            access.log(connection, username, "sign out", reason)
    for key in list(st.session_state.keys()):
        if key.startswith(("auth_", "enroll_")):
            del st.session_state[key]
    if reason:
        st.session_state["auth_notice"] = reason


def _heading(text: str) -> None:
    st.markdown(f"### Ledgerly · Business books")
    st.markdown(f"**{text}**")


def _owner_setup(db_path: Path) -> None:
    with _centered():
        _heading("Create the owner account")
        st.caption("This is the first time the app is opened. The owner can add other people and choose which "
                   "businesses each can open. You will set up an authenticator app next.")
        with st.form("owner_setup"):
            username = st.text_input("Username")
            name = st.text_input("Your name (optional)")
            password = st.text_input("Password", type="password", help=f"At least {auth.MIN_PASSWORD} characters.")
            again = st.text_input("Repeat the password", type="password")
            if st.form_submit_button("Continue", type="primary"):
                if password != again:
                    st.error("The two passwords do not match.")
                else:
                    try:
                        with db.connect(db_path) as connection:
                            auth.create_user(connection, username, password, display_name=name, is_owner=True)
                            access.log(connection, username, "owner created")
                        st.session_state["auth_enroll"] = auth.clean_username(username)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


def _enroll(db_path: Path, username: str) -> None:
    with db.connect(db_path) as connection:
        user = auth.get_user(connection, username)
    if not user:
        st.session_state.pop("auth_enroll", None)
        st.rerun()
    with _centered():
        codes = st.session_state.get("auth_codes")
        if codes:
            _heading("Save your recovery codes")
            st.warning("Each code works once if you lose your phone. They are shown only now. "
                       "Print them or keep them in a password manager.")
            st.code("\n".join(codes), language=None)
            st.download_button("Download the codes", "\n".join(codes) + "\n", file_name="ledgerly-recovery-codes.txt")
            saved = st.checkbox("I have saved these codes")
            if st.button("Open Ledgerly", type="primary", disabled=not saved):
                _sign_in(db_path, username, "mfa set up")
            return
        _heading("Set up your authenticator app")
        if user["must_change"]:
            st.info("Choose a new password before you continue.")
            with st.form("enroll_password"):
                new = st.text_input("New password", type="password")
                again = st.text_input("Repeat the new password", type="password")
                if st.form_submit_button("Save password", type="primary"):
                    if new != again:
                        st.error("The two passwords do not match.")
                    else:
                        try:
                            with db.connect(db_path) as connection:
                                auth.set_password(connection, username, new)
                                access.log(connection, username, "password changed", "first sign-in")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
            return
        secret = st.session_state.setdefault("enroll_secret", auth.new_secret())
        uri = auth.provisioning_uri(username, secret)
        st.write("1. Open an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy) "
                 "and scan this code.")
        st.image(auth.qr_png(uri), width=220)
        with st.expander("Cannot scan? Type the key instead"):
            st.code(secret, language=None)
        st.write("2. Type the 6-digit code the app shows.")
        with st.form("enroll_code"):
            code = st.text_input("6-digit code", max_chars=7)
            if st.form_submit_button("Turn on", type="primary"):
                try:
                    with db.connect(db_path) as connection:
                        st.session_state["auth_codes"] = auth.enable_mfa(connection, username, secret, code)
                        access.log(connection, username, "mfa enabled")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def _login(db_path: Path) -> None:
    with _centered():
        _heading("Sign in")
        if st.session_state.get("auth_notice"):
            st.info(st.session_state["auth_notice"])
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            code = st.text_input("6-digit code (or a recovery code)", help="From your authenticator app.")
            if st.form_submit_button("Sign in", type="primary"):
                with db.connect(db_path) as connection:
                    status, user = auth.attempt_login(connection, username, password, code)
                    who = auth.clean_username(username)
                    if status == "ok":
                        pass
                    elif status == "enroll":
                        access.log(connection, who, "password ok", "setting up MFA or new password")
                    elif status == "locked":
                        access.log(connection, who, "locked", f"too many attempts, locked {auth.LOCK_MINUTES} minutes")
                    elif status == "disabled":
                        access.log(connection, who, "failed sign in", "account turned off")
                    else:
                        access.log(connection, who, "failed sign in", "wrong username, password or code")
                if status == "ok":
                    _sign_in(db_path, who)
                elif status == "enroll":
                    st.session_state["auth_enroll"] = who
                    st.rerun()
                else:
                    time.sleep(0.8)
                    st.error({"locked": f"Too many wrong attempts. Try again in {auth.LOCK_MINUTES} minutes.",
                              "disabled": "This account is turned off. Ask the owner."}.get(
                        status, "The username, password or code is not right."))


def _no_access(db_path: Path, username: str) -> None:
    with _centered():
        _heading("No access")
        st.error(f"{username} has not been given access to any business. Ask the owner to add you.")
        st.button("Sign out", on_click=sign_out, args=(db_path,))


def gate(db_path: Path) -> dict[str, Any]:
    """Show the right sign-in screen and stop, or return the signed-in person."""
    with db.connect(db_path) as connection:
        access.ensure_schema(connection)
        auth.ensure_schema(connection)
    if AUTH_OFF:
        return {"username": "local", "display": "local", "is_owner": True, "ids": None, "enabled": False}
    username = st.session_state.get("auth_user")
    if username:
        if time.time() - st.session_state.get("auth_seen", 0) > INACTIVITY_SECONDS:
            sign_out(db_path, "You were signed out after a period of inactivity.")
            st.rerun()
        st.session_state["auth_seen"] = time.time()
        with db.connect(db_path) as connection:
            user = auth.get_user(connection, username)
            ids = None if user and user["is_owner"] else access.business_ids_for(connection, username)
        if not user or not user["active"]:
            sign_out(db_path, "Your account is no longer active.")
            st.rerun()
        if ids is not None and not ids:
            _no_access(db_path, username)
            st.stop()
        return {"username": username, "display": user["display_name"] or username,
                "is_owner": bool(user["is_owner"]), "ids": ids, "enabled": True}
    with db.connect(db_path) as connection:
        empty = auth.user_count(connection) == 0
    pending = st.session_state.get("auth_enroll")
    if pending:
        _enroll(db_path, pending)
    elif empty:
        _owner_setup(db_path)
    else:
        _login(db_path)
    st.stop()
