import httpx
import pandas as pd
import plotly.express as px
import streamlit as st
from dashboard.api_client import get
from dashboard.formatting import money, pct

st.set_page_config(page_title="Issuer Exposure", page_icon="📊", layout="wide")
st.title("Issuer Exposure")
st.markdown(
    "Look up every tracked fund's exposure to a single ticker "
    "(rolled up by issuer, so GOOG and GOOGL sum together)."
)

col_input, col_btn = st.columns([3, 1])
with col_input:
    ticker_raw = st.text_input(
        "Ticker",
        value=st.session_state.get("exposure_ticker", ""),
        placeholder="AAPL",
    )
with col_btn:
    st.write("")  # spacer to align with input label
    st.write("")
    submitted = st.button("Search", type="primary")

if submitted and ticker_raw and ticker_raw.strip():
    st.session_state["exposure_ticker"] = ticker_raw.strip().upper()

ticker = st.session_state.get("exposure_ticker", "")
if not ticker:
    st.info("Enter a ticker above and click Search.")
    st.stop()

st.subheader(f"Exposure to {ticker}")

lookthrough = st.checkbox(
    "Include ETF look-through",
    value=False,
    help="Add weight that each fund holds via ETFs (e.g. SPY) that contain this ticker.",
)

try:
    params = {"lookthrough": "true"} if lookthrough else None
    data = get(f"/exposure/{ticker}", params)
except httpx.HTTPStatusError as e:
    if e.response.status_code == 404:
        st.warning(f"No tracked fund holds {ticker}.")
        st.stop()
    st.error(f"API returned {e.response.status_code}")
    with st.expander("response body"):
        st.code(e.response.text)
    st.stop()
except httpx.HTTPError as e:
    st.error(f"could not reach API: {e}")
    st.stop()

exposures = data["exposures"]
sorted_exps = sorted(exposures, key=lambda e: e["weight"], reverse=True)

# Bar chart of per-fund weights
fig = px.bar(
    x=[e["weight"] for e in sorted_exps],
    y=[e["fund_name"] for e in sorted_exps],
    orientation="h",
    labels={"x": "Weight", "y": "Fund"},
)
fig.update_layout(
    margin={"l": 0, "r": 0, "t": 0, "b": 0},
    height=max(200, 32 * len(sorted_exps) + 60),
    xaxis_tickformat=".1%",
    yaxis={"autorange": "reversed"},
)
st.plotly_chart(fig, use_container_width=True)

# Detail table
def _row(e: dict) -> dict:
    base = {
        "Fund": e["fund_name"],
        "CIK": e["fund_cik"],
        "Quarter": e["quarter"],
        "Ticker": e["ticker"],
        "Direct weight": pct(e["weight"]),
        "Value": money(e["value_usd"]),
    }
    if lookthrough:
        base["Look-through weight"] = pct(e.get("lookthrough_weight"))
    return base


st.dataframe(
    pd.DataFrame([_row(e) for e in sorted_exps]),
    use_container_width=True,
    hide_index=True,
)
issuer_key = data["exposures"][0]["issuer_key"]
cov_note = ""
if lookthrough and data["exposures"]:
    cov = data["exposures"][0].get("lookthrough_coverage")
    if cov is not None:
        cov_note = f" (ETF-constituent coverage {pct(cov)})"
st.caption(
    f"{len(exposures)} fund(s) hold {ticker} (issuer_key={issuer_key}).{cov_note}"
)

with st.expander("Data notes"):
    for note in data.get("data_notes", []):
        st.markdown(f"- {note}")
