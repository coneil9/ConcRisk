import os

import streamlit as st

st.set_page_config(page_title="ConcRisk", page_icon="📊", layout="wide")

st.title("ConcRisk")
st.markdown(
    """
Concentration risk analytics for institutional equity portfolios,
built on public SEC 13F filings.

Use the sidebar to navigate:

- **Overview** — concentration-limit breaches across every tracked fund
- **Fund Detail** — one fund's KPIs and holdings breakdown
- **Issuer Exposure** — every fund's exposure to one ticker
- **Compare** — two funds side by side
"""
)

api_url = os.environ.get("CONCRISK_API_URL", "http://localhost:8000")
st.info(f"Reading from `{api_url}`.")

st.caption(
    "13F is quarterly and filed up to 45 days after quarter end — "
    "holdings shown here can be up to ~135 days stale."
)
