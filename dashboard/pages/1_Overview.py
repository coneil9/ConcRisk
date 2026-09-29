import httpx
import pandas as pd
import streamlit as st
from dashboard.api_client import clear_cache, get
from dashboard.formatting import pct

WEIGHT_METRICS = {"hhi", "issuer_weight", "sector_weight", "top_n_weight"}


st.set_page_config(page_title="Overview", page_icon="📊", layout="wide")
st.title("Concentration Breaches")


def _format_value(metric: str, value: float) -> str:
    if metric in WEIGHT_METRICS:
        return pct(value)
    return f"{value:.2f}"


col1, col2, _ = st.columns([1, 1, 3])
with col1:
    severity = st.radio(
        "Severity",
        ["all", "warning", "breach"],
        horizontal=True,
        index=0,
    )
with col2:
    quarter = st.text_input("Quarter (blank = each fund's latest)", placeholder="2026Q1")

params: dict[str, str] = {}
if severity != "all":
    params["severity"] = severity
if quarter:
    params["quarter"] = quarter

try:
    data = get("/breaches", params or None)
except httpx.HTTPStatusError as e:
    st.error(f"API returned {e.response.status_code}")
    with st.expander("response body"):
        st.code(e.response.text)
    st.stop()
except httpx.HTTPError as e:
    st.error(f"could not reach API: {e}")
    st.stop()

breaches = data["breaches"]
if not breaches:
    st.success("No breaches — portfolios are within limits for the selected filters.")
else:
    display_rows = [
        {
            "Fund CIK": b["fund_cik"],
            "Quarter": b["quarter"],
            "Rule": b["rule_id"],
            "Severity": b["severity"],
            "Observed": _format_value(b["metric"], b["observed"]),
            "Threshold": _format_value(b["metric"], b["threshold"]),
            "Scope": b["scope_key"] or "—",
        }
        for b in breaches
    ]
    st.dataframe(
        pd.DataFrame(display_rows),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"{len(breaches)} breach(es) shown.")

with st.expander("Data notes"):
    for note in data.get("data_notes", []):
        st.markdown(f"- {note}")

if st.button("Refresh", type="secondary"):
    clear_cache()
    st.rerun()
