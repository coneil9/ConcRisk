import httpx
import pandas as pd
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

# Phase 7 toggles
col_opt, col_lt = st.columns(2)
with col_opt:
    options_scenario = st.selectbox(
        "Options scenario",
        ["none", "ignore", "atm", "notional"],
        index=0,
        help="atm = CALL ±0.5 / PUT ∓0.5; notional = ±1.0; ignore = 0. "
        "'none' excludes options entirely (SPEC §6 default).",
    )
with col_lt:
    lookthrough = st.checkbox(
        "ETF look-through",
        value=False,
        help="Expand ETF positions into their underlying constituents.",
    )

params: dict[str, str | int | bool] = {"quarter": quarter}
if options_scenario != "none":
    params["options_scenario"] = options_scenario
if lookthrough:
    params["lookthrough"] = "true"

try:
    conc = get(f"/funds/{fund['cik']}/concentration", params)
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
    "Sector labels come from the yfinance backfill — run "
    "`python -m concrisk.etl.sectors` to populate."
)

# Phase 7: options scenario breakdown
if conc.get("options_scenario") and conc.get("combined_issuers"):
    st.divider()
    st.subheader(f"Combined issuer exposure ({conc['options_scenario']} scenario)")
    combined = conc["combined_issuers"][:15]
    issuers = [c["issuer_key"] for c in combined]
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_bar(
        x=[c["equity_weight"] for c in combined],
        y=issuers,
        orientation="h",
        name="Equity",
    )
    fig.add_bar(
        x=[c["option_delta_weight"] for c in combined],
        y=issuers,
        orientation="h",
        name=f"Option δ ({conc['options_scenario']})",
    )
    fig.update_layout(
        barmode="relative",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=max(200, 28 * len(combined) + 60),
        xaxis_tickformat=".1%",
        yaxis={"autorange": "reversed"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Options scenario `{conc['options_scenario']}`: combined weight = "
        "(equity + Σ δ × U_option) / equity NAV. Can exceed 100% when "
        "options stack onto equity."
    )

# Phase 7: look-through weights
if conc.get("lookthrough") and conc.get("lookthrough_weights"):
    st.divider()
    cov = conc.get("lookthrough_coverage") or 0.0
    st.subheader(f"ETF look-through (coverage {pct(cov)})")
    expanded = sorted(
        conc["lookthrough_weights"].items(), key=lambda kv: -kv[1]
    )[:15]
    fig = px.bar(
        x=[v for _, v in expanded],
        y=[k for k, _ in expanded],
        orientation="h",
        labels={"x": "Expanded weight", "y": "Ticker"},
    )
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=max(200, 28 * len(expanded) + 60),
        xaxis_tickformat=".1%",
        yaxis={"autorange": "reversed"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Expanded = direct weight + Σ (ETF weight × constituent weight). "
        f"Coverage {pct(cov)} = fraction of ETF holdings we had constituent "
        "data for; the rest stayed as the ETF ticker."
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

# Correlation clusters
st.divider()
st.subheader("Correlation clusters")
try:
    clusters_data = get(f"/funds/{fund['cik']}/clusters", {"quarter": quarter})
    cluster_rows = clusters_data["clusters"]
    if clusters_data.get("insufficient_price_data"):
        st.info(
            "Price history is thin for this quarter — "
            "run `python -m concrisk.etl.prices` to backfill."
        )
    if cluster_rows:
        display = pd.DataFrame(
            [
                {
                    "Members": ", ".join(c["tickers"]),
                    "Combined weight": pct(c["weight"]),
                    "Avg correlation": f"{c['avg_correlation']:.2f}",
                }
                for c in cluster_rows
            ]
        )
        st.dataframe(display, use_container_width=True, hide_index=True)
        n_missing = len(clusters_data.get("missing_tickers", []))
        st.caption(
            f"Clusters cut at ρ ≥ {clusters_data['rho_threshold']}; "
            f"min weight {pct(clusters_data['min_weight'])}; "
            f"{n_missing} ticker(s) excluded for missing prices."
        )
    else:
        st.caption("No correlated clusters at this threshold.")
except (httpx.HTTPStatusError, httpx.HTTPError) as e:
    st.warning(f"Clusters unavailable: {e}")

with st.expander("Data notes"):
    for note in conc.get("data_notes", []):
        st.markdown(f"- {note}")
