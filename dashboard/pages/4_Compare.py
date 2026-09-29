import httpx
import plotly.express as px
import streamlit as st
from dashboard.api_client import get
from dashboard.formatting import pct

st.set_page_config(page_title="Compare", page_icon="📊", layout="wide")
st.title("Compare Funds")

try:
    funds_payload = get("/funds")
except (httpx.HTTPStatusError, httpx.HTTPError) as e:
    st.error(f"Could not load funds: {e}")
    st.stop()

funds_with_data = [f for f in funds_payload["funds"] if f["latest_quarter"]]
if len(funds_with_data) < 2:
    st.warning(
        "Need at least two funds with loaded data. Run the ETL pipeline for a couple funds first."
    )
    st.code(
        "uv run python -m concrisk.etl.pipeline --fund 0001067983 --fund 0001336528 --quarters 2",
        language="bash",
    )
    st.stop()

labels = [f"{f['name']} ({f['cik']})" for f in funds_with_data]

col_a, col_b = st.columns(2)
with col_a:
    idx_a = st.selectbox("Fund A", range(len(labels)), format_func=lambda i: labels[i], key="cmp_a")
with col_b:
    default_b = 1 if len(labels) > 1 else 0
    idx_b = st.selectbox(
        "Fund B",
        range(len(labels)),
        format_func=lambda i: labels[i],
        index=default_b,
        key="cmp_b",
    )

if idx_a == idx_b:
    st.info("Pick two different funds to compare.")
    st.stop()

fund_a = funds_with_data[idx_a]
fund_b = funds_with_data[idx_b]

quarter = st.text_input("Quarter (blank = each fund's latest available)", placeholder="2026Q1")

params = {"ciks": f"{fund_a['cik']},{fund_b['cik']}"}
if quarter:
    params["quarter"] = quarter

try:
    data = get("/compare", params)
except httpx.HTTPStatusError as e:
    st.error(f"API returned {e.response.status_code}")
    with st.expander("body"):
        st.code(e.response.text)
    st.stop()
except httpx.HTTPError as e:
    st.error(f"could not reach API: {e}")
    st.stop()

by_cik = {f["fund_cik"]: f for f in data["funds"]}
snap_a = by_cik[fund_a["cik"]]
snap_b = by_cik[fund_b["cik"]]


def _kpi_column(container, fund_meta: dict, snap: dict) -> None:
    container.subheader(f"{fund_meta['name']} — {snap['quarter']}")
    c1, c2 = container.columns(2)
    c3, c4 = container.columns(2)
    c1.metric("HHI", f"{snap['hhi']:.4f}")
    c2.metric("Effective N", f"{snap['effective_n']:.1f}")
    c3.metric("Top 10", pct(snap["top10"]))
    c4.metric(
        f"Largest — {snap['largest_issuer']['issuer_key']}",
        pct(snap["largest_issuer"]["weight"]),
    )


col_a2, col_b2 = st.columns(2)
_kpi_column(col_a2, fund_a, snap_a)
_kpi_column(col_b2, fund_b, snap_b)

st.divider()

# Top-10 issuer weights side by side
st.subheader("Top-10 holdings by weight")


@st.cache_data(ttl=60, show_spinner=False)
def _top_holdings(cik: str, quarter_str: str | None) -> list[dict]:
    p: dict[str, str | int] = {"top": 10}
    if quarter_str:
        p["quarter"] = quarter_str
    return get(f"/funds/{cik}/holdings", p)["holdings"]


def _holdings_bar(container, cik: str, quarter_str: str | None) -> None:
    rows = _top_holdings(cik, quarter_str)
    labels = [r["ticker"] or r["cusip"] for r in rows]
    weights = [r["weight"] for r in rows]
    fig = px.bar(
        x=weights,
        y=labels,
        orientation="h",
        labels={"x": "Weight", "y": ""},
    )
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=max(200, 32 * len(rows) + 60),
        xaxis_tickformat=".1%",
        yaxis={"autorange": "reversed"},
    )
    container.plotly_chart(fig, use_container_width=True)


col_a3, col_b3 = st.columns(2)
_holdings_bar(col_a3, fund_a["cik"], snap_a["quarter"])
_holdings_bar(col_b3, fund_b["cik"], snap_b["quarter"])

with st.expander("Data notes"):
    for note in data.get("data_notes", []):
        st.markdown(f"- {note}")
