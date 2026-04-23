"""
auth_handler.py  –  Google Earth Engine authentication for hosted Streamlit apps.

Drop this file next to App.py.  Then replace the EE-init block in App.py with:

    from auth_handler import render_auth_gate
    if not render_auth_gate():
        st.stop()

That's it.  The rest of your app runs unchanged once the user is authenticated.
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import streamlit as st
import ee


# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

def _write_credentials(cred_json: str, project_id: str) -> None:
    """Write credentials to the standard Earth Engine path and initialize."""
    ee_dir = os.path.expanduser("~/.config/earthengine")
    os.makedirs(ee_dir, exist_ok=True)
    cred_path = os.path.join(ee_dir, "credentials")
    with open(cred_path, "w") as f:
        f.write(cred_json)
    ee.Initialize(project=project_id)


def _try_initialize(project_id: str, cred_json: str | None = None) -> tuple[bool, str]:
    """
    Attempt EE initialization.
    Returns (success: bool, error_message: str).
    """
    try:
        if cred_json:
            _write_credentials(cred_json, project_id)
        else:
            ee.Initialize(project=project_id)
        # Quick smoke-test
        ee.Number(1).getInfo()
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def render_auth_gate() -> bool:
    """
    Show the authentication UI if the user is not yet authenticated.
    Returns True when EE is ready; False when the app should st.stop().

    Usage in App.py:
        from auth_handler import render_auth_gate
        if not render_auth_gate():
            st.stop()
    """
    # Already authenticated in this session?
    if st.session_state.get("ee_authenticated"):
        return True

    # ── Page header ──────────────────────────────────────────────────────
    st.markdown(
        """
        <h2 style='margin-bottom:0'>🌍 Urban Heat Island Analyzer</h2>
        <p style='color:#888;margin-top:4px'>Powered by Google Earth Engine · Landsat + MODIS</p>
        <hr>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("🔐 Connect your Google Earth Engine account")
    st.markdown(
        "This app runs entirely on **your own** GEE quota — no data is stored. "
        "Authentication is session-only and cleared when you close the tab."
    )

    # ── Method selector ──────────────────────────────────────────────────
    method = st.radio(
        "Choose Authentication Method:",
        ["📁 Upload Credentials File", "💻 Local / Server (already authenticated)"],
        horizontal=False,
    )

    st.markdown("---")

    # ── Project ID (shared between both methods) ─────────────────────────
    with st.container(border=True):
        st.markdown("#### 📋 Authentication Details")
        project_id = st.text_input(
            "Google Earth Engine Project ID *",
            placeholder="my-earth-engine-project",
            help=(
                "Found at https://console.cloud.google.com/ → select your project → "
                "the ID is shown at the top (e.g. `ee-myname-001`)."
            ),
        )

        # ── Branch: upload method ─────────────────────────────────────────
        if "Upload" in method:
            st.markdown("#### 📂 Upload Earth Engine Credentials")

            with st.expander("🔵 Quick Access: Where is my credentials file?", expanded=True):
                st.markdown(
                    textwrap.dedent("""
                    | OS | Path |
                    |---|---|
                    | **Windows** | `C:\\Users\\YOUR_NAME\\.config\\earthengine\\credentials` |
                    | **Mac / Linux** | `~/.config/earthengine/credentials` |

                    The file is named exactly **`credentials`** (no extension).
                    """)
                )

            with st.expander("📘 First Time? How to Get Your Credentials File"):
                st.markdown(
                    textwrap.dedent("""
                    **Step 1 – Get a free GEE account**
                    → [https://earthengine.google.com/signup/](https://earthengine.google.com/signup/)
                    *(select "For research / study")*

                    **Step 2 – Install the Earth Engine Python API** *(do this once on your computer)*
                    ```
                    pip install earthengine-api
                    ```

                    **Step 3 – Authenticate**
                    ```
                    earthengine authenticate
                    ```
                    A browser window will open → sign in with the Google account you
                    registered with → approve access.

                    **Step 4 – Find the credentials file** using the table above and upload it here.
                    """)
                )

            uploaded = st.file_uploader(
                "Upload Earth Engine Credentials File",
                type=None,
                help="Upload the file named exactly `credentials` (no extension).",
            )

            st.info(
                "🔒 Your session stays active while this browser tab is open. "
                "Close the tab to end your session.",
                icon="ℹ️",
            )

            auth_btn = st.button("🔑 Authenticate", type="primary", use_container_width=False)

            if auth_btn:
                if not project_id.strip():
                    st.error("Please enter your GEE Project ID.")
                elif uploaded is None:
                    st.error("Please upload your credentials file.")
                else:
                    try:
                        cred_text = uploaded.read().decode("utf-8")
                        # Validate JSON
                        json.loads(cred_text)
                    except Exception:
                        st.error(
                            "❌ The uploaded file does not look like a valid credentials file. "
                            "Make sure you uploaded the file named `credentials` (no extension)."
                        )
                        return False

                    with st.spinner("Connecting to Google Earth Engine…"):
                        ok, err = _try_initialize(project_id.strip(), cred_text)

                    if ok:
                        st.session_state["ee_authenticated"] = True
                        st.session_state["ee_project_id"] = project_id.strip()
                        st.success("✅ Authenticated! Loading the app…")
                        st.rerun()
                    else:
                        st.error(
                            f"❌ Authentication failed.\n\n```\n{err}\n```\n\n"
                            "**Common fixes:**\n"
                            "- Double-check your Project ID (no spaces, all lowercase)\n"
                            "- Make sure your GEE project is active at "
                            "[console.cloud.google.com](https://console.cloud.google.com)\n"
                            "- Re-run `earthengine authenticate` and upload the new file"
                        )

        # ── Branch: local / server method ────────────────────────────────
        else:
            st.markdown("#### 💻 Local Method (For Forked/Cloned Repository)")

            st.success(
                "**Use this method if you:**\n"
                "- Forked or cloned this repository to your local machine\n"
                "- Are running `streamlit run App.py` locally\n"
                "- Have already authenticated with Google Earth Engine on your computer",
                icon="✅",
            )

            with st.expander("📘 Complete Setup Steps for Local Development"):
                st.markdown(
                    textwrap.dedent("""
                    1. `git clone https://github.com/YOUR_REPO`
                    2. `pip install -r requirements.txt`
                    3. `earthengine authenticate`
                    4. `streamlit run App.py`
                    """)
                )

            st.warning(
                "⚠️ **Important:** This method requires:\n"
                "- You've run `earthengine authenticate` on your computer\n"
                "- You're running the app locally (not on a website)\n"
                "- Credentials file exists at `~/.config/earthengine/credentials`\n\n"
                "**If using the hosted website, choose 'Upload Credentials' method instead.**",
            )

            st.info(
                "🔒 Your session stays active while this browser tab is open. "
                "Close the tab to end your session.",
                icon="ℹ️",
            )

            auth_btn = st.button("🔑 Authenticate", type="primary", use_container_width=False)

            if auth_btn:
                if not project_id.strip():
                    st.error("Please enter your GEE Project ID.")
                else:
                    with st.spinner("Connecting to Google Earth Engine…"):
                        ok, err = _try_initialize(project_id.strip())

                    if ok:
                        st.session_state["ee_authenticated"] = True
                        st.session_state["ee_project_id"] = project_id.strip()
                        st.success("✅ Authenticated! Loading the app…")
                        st.rerun()
                    else:
                        st.error(
                            f"❌ Authentication failed.\n\n```\n{err}\n```\n\n"
                            "Make sure you have run `earthengine authenticate` locally."
                        )

    return False  # Not yet authenticated
