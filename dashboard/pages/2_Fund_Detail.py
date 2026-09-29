import httpx
import plotly.express as px
import streamlit as st
from dashboard.api_client import get
from dashboard.formatting import money, pct

st.set_page_config(page_title="Fund Detail", page_icon="📊", layout="wide")
st.title("Fund Detail")

try:
    funds_payload = get("/funds")
except (httpx.HTTPStatusError, httpx.HTTPError) as e:
    st.error(f"Could not load funds: {e}")
    st.stop()

funds_with_data = [f for f in funds_payload["funds"] if f["latest_quarter"]]
if not funds_with_data:
    st.warning("No funds have data yet. Load some via the ETL pipeline:")
    st.code(
        "uv run python -m concrisk.etl.pipeline --fund 0001336528 --quarters 2",
        language="bash",
    )
    st.stop()

col_fund, col_qtr = st.columns([3, 1])
with col_fund:
    labels = [f"{f['name']} ({f['cik']})" for f in funds_with_data]
    idx = st.selectbox("Fund", range(len(labels)), format_func=lambda i: labels[i])
    fund = funds_with_data[idx]
with col_qtr:
    quarters = get(f"/funds/{fund['cik']}/quarters")["quarters"]
    if not quarters:
        st.error("no quarters available for this fund")
        st.stop()
    quarter = st.selectbox("Quarter", quarters, index=len(quarters) - 1)

try:
    conc = get(f"/funds/{fund['cik']}/concentration", {"quarter": quarter})
    holdings = get(f"/funds/{fund['cik']}/holdings", {"quarter": quarter, "top": 25})
    history = get(f"/funds/{fund['cik']}/concentration/history")
except (httpx.HTTPStatusError, httpx.HTTPError) as e:
    st.error(f"Load failed: {e}")
    st.stop()

# KPI row
c1, c2, c3, c4 = st.columns(4)
c1.metric("HHI", f"{conc['hhi']:.4f}")
c2.metric("Effective N", f"{conc['effective_n']:.1f}")
c3.metric("Top 10", pct(conc["top10"]))
li = conc["largest_issuer"]
c4.metric(f"Largest issuer — {li['issuer_key']}", pct(li["weight"]))

st.divider()

# Treemap of top-25 holdings
st.subheader("Holdings (top 25 by weight)")
labels_h = [h["ticker"] or h["cusip"] for h in holdings["holdings"]]
weights_h = [h["weight"] for h in holdings["holdings"]]
hover = [
    f"{h.get('name') or h['cusip']}<br>{money(h['value_usd'])} — {pct(h['weight'])}"
    for h in holdings["holdings"]
]
if labels_h:
    fig = px.treemap(
        names=labels_h,
        parents=[""] * len(labels_h),
        values=weights_h,
        color=weights_h,
        color_continuous_scale="Blues",
        custom_data=[hover],
    )
    fig.update_traces(hovertemplate="%{customdata[0]}<extra></extra>")
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0}, height=500)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Portfolio total: {money(holdings['total_value_usd'])} "
        f"across {len(holdings['holdings'])} shown positions."
    )
else:
    st.info("no holdings")

st.divider()

# Sector bar
st.subheader("Sector Weights")
sw = conc["sector_weights"]
if sw:
    sectors_sorted = sorted(sw.items(), key=lambda kv: kv[1])
    fig = px.bar(
        x=[v for _, v in sectors_sorted],
        y=[k for k, _ in sectors_sorted],
        orientation="h",
        labels={"x": "Weight", "y": "Sector"},
    )
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=max(150, 30 * len(sectors_sorted) + 60),
        xaxis_tickformat=".1%",
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("no sector data")
st.caption(
    "Sector labels come from yfinance in Phase 7 — real portfolios "
    "currently show as 'Unclassified'."
)

st.divider()

# HHI history
st.subheader("HHI over time")
hist_rows = history["history"]
if len(hist_rows) > 1:
    fig = px.line(
        x=[r["quarter"] for r in hist_rows],
        y=[r["hhi"] for r in hist_rows],
        markers=True,
        labels={"x": "Quarter", "y": "HHI"},
    )
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0}, height=250)
    st.plotly_chart(fig, use_container_width=True)
elif hist_rows:
    st.info("only one quarter of data — history plot needs at least two.")
else:
    st.info("no history")

with st.expander("Data notes"):
    for note in conc.get("data_notes", []):
        st.markdown(f"- {note}")
