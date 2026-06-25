"""
Optional basic authentication for the Streamlit app.
Enable by setting AUTH_ENABLED=true in the environment or .env file.
"""

from __future__ import annotations
import os
import streamlit as st


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _check_password(entered: str, stored_hash: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(entered.encode(), stored_hash.encode())
    except Exception:
        return False


def require_auth() -> bool:
    """
    Show a login form if AUTH_ENABLED=true.
    Returns True if the user is authenticated (or auth is disabled).
    """
    if _env("AUTH_ENABLED", "false").lower() != "true":
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("SAP Security Note Analyzer")
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        expected_user = _env("AUTH_USERNAME", "admin")
        stored_hash = _env("AUTH_PASSWORD_HASH", "")

        if username == expected_user and stored_hash and _check_password(password, stored_hash):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid username or password.")

    return False
