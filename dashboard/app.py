"""
Streamlit dashboard for Shepherd Capital Fund Tracker.

Run with: streamlit run dashboard/app.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Ensure the project root is on sys.path so src.* imports work
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.database import get_session, init_db
from src.utils import get_config_value

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Shepherd Capital — Fund Tracker",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# ---------------------------------------------------------------------------
# Prosus theme — CSS injection + chart palette
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

*, html, body, .stApp {
    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;
}
.stApp { background-color: #FFFFFF; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #163180 !important;
    border-right: none;
}
[data-testid="stSidebar"] * { color: #E8EDF8 !important; }
[data-testid="stSidebar"] h1 {
    color: #FFFFFF !important;
    font-size: 1.05rem !important;
    font-weight: 600 !important;
    line-height: 1.45 !important;
    letter-spacing: 0.01em;
}
[data-testid="stSidebar"] p { color: #A8B8D8 !important; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    border-radius: 0 4px 4px 0 !important;
    padding: 6px 10px !important;
    margin-bottom: 2px;
    transition: background 0.15s;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background-color: rgba(255,255,255,0.08) !important;
}
[data-testid="stSidebar"] [role="radio"][aria-checked="true"],
[data-testid="stSidebar"] [aria-selected="true"] {
    background-color: rgba(255,255,255,0.12) !important;
    border-left: 3px solid #FFFFFF !important;
}
[data-testid="stSidebar"] .stAlert {
    background-color: rgba(245,166,35,0.15) !important;
    border-color: #F5A623 !important;
}

/* ── Page headings ── */
h1 {
    color: #1E3DA5 !important;
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.01em;
    margin-bottom: 1.1rem !important;
    border-bottom: none;
    padding-bottom: 0;
}
h2 {
    color: #1E3DA5 !important;
    font-size: 1.15rem !important;
    font-weight: 600 !important;
    border-bottom: none;
    padding-bottom: 0;
    margin-top: 1.2rem !important;
    margin-bottom: 0.6rem !important;
}
h3 {
    color: #333333 !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
}

/* ── Metric cards ── */
[data-testid="metric-container"] {
    background: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-top: 3px solid #1E3DA5;
    border-radius: 2px;
    padding: 1rem 1.2rem !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #666666 !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: #1E3DA5 !important;
}

/* ── Buttons ── */
.stButton > button {
    font-family: 'Inter', Arial, sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    border-radius: 2px !important;
    transition: background 0.15s, color 0.15s;
}
.stButton > button[data-testid="baseButton-primary"],
.stButton > button[kind="primary"] {
    background-color: #1E3DA5 !important;
    color: #FFFFFF !important;
    border: none !important;
}
.stButton > button[data-testid="baseButton-primary"]:hover,
.stButton > button[kind="primary"]:hover {
    background-color: #163180 !important;
}
.stButton > button[data-testid="baseButton-secondary"],
.stButton > button[kind="secondary"] {
    background-color: #FFFFFF !important;
    color: #1E3DA5 !important;
    border: 1.5px solid #1E3DA5 !important;
}
.stButton > button[data-testid="baseButton-secondary"]:hover,
.stButton > button[kind="secondary"]:hover {
    background-color: #F0F4FF !important;
}

/* ── Download buttons ── */
.stDownloadButton > button {
    background-color: transparent !important;
    color: #1E3DA5 !important;
    border: 1.5px solid #1E3DA5 !important;
    font-weight: 600 !important;
    border-radius: 2px !important;
}
.stDownloadButton > button:hover {
    background-color: #1E3DA5 !important;
    color: #FFFFFF !important;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] thead tr th,
[data-testid="stDataFrame"] th {
    background-color: #1E3DA5 !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
    font-size: 0.75rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
[data-testid="stDataFrame"] tr:nth-child(even) td {
    background-color: #F5F7FA !important;
}
[data-testid="stDataFrame"] {
    border: 1px solid #E0E0E0;
    border-radius: 2px;
    overflow: hidden;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 1px solid #E0E0E0 !important;
    border-radius: 2px !important;
    background: #FFFFFF !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    color: #1E3DA5 !important;
}

/* ── Inputs ── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stTextInput"] > div > div > input {
    border-color: #E0E0E0 !important;
    border-radius: 2px !important;
}
[data-testid="stSelectbox"] > div > div:focus-within,
[data-testid="stTextInput"] > div > div:focus-within {
    border-color: #1E3DA5 !important;
    box-shadow: 0 0 0 2px rgba(30,61,165,0.12) !important;
}

/* ── Progress bar ── */
.stProgress > div > div > div > div {
    background-color: #1E3DA5 !important;
}

/* ── Alert boxes ── */
div[data-testid="stInfo"] {
    background-color: rgba(30,61,165,0.05) !important;
    border-left-color: #1E3DA5 !important;
}
div[data-testid="stSuccess"] {
    background-color: rgba(0,168,120,0.07) !important;
    border-left-color: #00A878 !important;
}
div[data-testid="stWarning"] {
    background-color: rgba(245,166,35,0.08) !important;
    border-left-color: #F5A623 !important;
}
div[data-testid="stError"] {
    background-color: rgba(217,48,37,0.07) !important;
    border-left-color: #D93025 !important;
}

/* ── Divider ── */
hr { border-color: #E0E0E0 !important; margin: 1.4rem 0 !important; }

/* ── Spinner ── */
.stSpinner > div { border-top-color: #1E3DA5 !important; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab"] { font-weight: 500 !important; color: #666666 !important; }
.stTabs [aria-selected="true"] { color: #1E3DA5 !important; border-bottom-color: #1E3DA5 !important; font-weight: 600 !important; }

/* ── Caption / muted text ── */
[data-testid="stCaptionContainer"], .stCaption { color: #666666 !important; font-size: 0.8rem !important; }
</style>
""", unsafe_allow_html=True)

# Prosus brand Plotly palette
_SPX_COLORS = ["#1E3DA5", "#F5A623", "#00A878", "#D93025", "#4A6FCC", "#163180", "#7A9ED8"]

def _spx_layout(**kwargs) -> dict:
    """Base Plotly layout using Prosus design tokens."""
    base = dict(
        font=dict(family="Inter, Helvetica Neue, Arial, sans-serif", color="#333333", size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=_SPX_COLORS,
        margin=dict(t=30, b=40, l=20, r=20),
        legend=dict(font=dict(size=11)),
        xaxis=dict(gridcolor="#EEEEEE", linecolor="#E0E0E0", zerolinecolor="#E0E0E0"),
        yaxis=dict(gridcolor="#EEEEEE", linecolor="#E0E0E0", zerolinecolor="#E0E0E0"),
    )
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_data() -> dict:
    session = get_session()
    data = {}
    for table, key in [
        ("sources", "sources"),
        ("extracted_recommendations", "recs"),
        ("portfolio_holdings", "holdings"),
        ("fund_performance", "perf"),
        ("prices", "prices"),
        ("ticker_map", "ticker_map"),
    ]:
        try:
            data[key] = pd.read_sql(f"SELECT * FROM {table}", session.bind)
        except Exception:
            data[key] = pd.DataFrame()
    return data


def get_data() -> dict:
    if "data" not in st.session_state or st.session_state.get("refresh_flag"):
        st.session_state["data"] = load_data()
        st.session_state["refresh_flag"] = False
    return st.session_state["data"]


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.markdown(
    "<h1 style='font-size:1.1rem;font-weight:700;color:#FFFFFF;letter-spacing:0.01em;"
    "line-height:1.4;padding:0.4rem 0 0.2rem 0;'>Shepherd Capital<br>Fund Tracker</h1>",
    unsafe_allow_html=True,
)
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    [
        "Overview",
        "Fund Performance",
        "Holdings",
        "Recommendation Explorer",
        "Source Articles",
        "Manual Review",
        "Refresh & Export",
        "Fair Value Analysis",
    ],
    key="page",
)

st.sidebar.markdown("---")
substack_url = get_config_value("sources", "substack_url", default="")
website_url = get_config_value("sources", "website_url", default="")
if "PASTE_" in str(substack_url):
    st.sidebar.warning("⚠️ Configure Substack URL in config.yaml")
if "PASTE_" in str(website_url):
    st.sidebar.warning("⚠️ Configure Website URL in config.yaml")

# ---------------------------------------------------------------------------
# Helper: run pipeline step
# ---------------------------------------------------------------------------

def run_step(label: str, fn):
    with st.spinner(f"Running: {label}..."):
        try:
            fn()
            st.success(f"{label} complete")
        except Exception as exc:
            st.error(f"{label} failed: {exc}")
    st.session_state["refresh_flag"] = True
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_overview():
    st.title("Overview")
    data = get_data()

    sources = data["sources"]
    recs = data["recs"]
    holdings = data["holdings"]
    perf = data["perf"]

    # ── Cover Page ──────────────────────────────────────────────────────────
    _site_url = get_config_value("sources", "website_url", default="https://www.shepherdcapital.com")
    _sub_url  = get_config_value("sources", "substack_url", default="https://shepherdcapital.substack.com")
    st.markdown(f"""
<div style="
    background: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-left: 5px solid #1E3DA5;
    border-radius: 4px;
    padding: 2rem 2.4rem 1.8rem 2.4rem;
    margin-bottom: 1.6rem;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
">
  <p style="
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #1E3DA5;
      margin: 0 0 0.4rem 0;
  ">Investment Strategy Overview</p>

  <h2 style="
      font-size: 1.6rem;
      font-weight: 700;
      color: #333333;
      margin: 0 0 0.2rem 0;
      border: none;
      padding: 0;
  ">Shepherd Capital</h2>

  <p style="font-size: 1rem; color: #666666; margin: 0 0 1.4rem 0; font-style: italic;">
      Systematic conviction investing — curated ideas, fundamental discipline
  </p>

  <p style="font-size: 0.97rem; color: #333333; line-height: 1.7; margin: 0 0 1.2rem 0;">
      Shepherd Capital is a research-driven equity strategy that identifies companies with
      durable competitive advantages trading at a discount to intrinsic value, or positioned
      for a fundamental re-rating as near-term headwinds resolve. The strategy draws on
      curated research published through <em>Shepherd Capital's</em> Substack and website,
      systematically extracting and stress-testing every buy-side idea against a multi-model
      valuation framework before it enters the portfolio.
  </p>

  <div style="display: flex; gap: 2.5rem; flex-wrap: wrap; margin-bottom: 1.4rem;">
    <div>
      <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.08em; color: #666666; margin: 0 0 0.25rem 0;">
          Investment Universe
      </p>
      <p style="font-size: 0.95rem; color: #333333; margin: 0;">
          Global listed equities, tilted toward mid- and large-cap
      </p>
    </div>
    <div>
      <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.08em; color: #666666; margin: 0 0 0.25rem 0;">
          Portfolio Construction
      </p>
      <p style="font-size: 0.95rem; color: #333333; margin: 0;">
          Equal-weighted, monthly rebalanced, benchmarked vs SPY · QQQ · URTH
      </p>
    </div>
    <div>
      <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.08em; color: #666666; margin: 0 0 0.25rem 0;">
          Idea Sourcing
      </p>
      <p style="font-size: 0.95rem; color: #333333; margin: 0;">
          Proprietary research pipeline — AI-extracted from published articles & deep-dives
      </p>
    </div>
    <div>
      <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.08em; color: #666666; margin: 0 0 0.25rem 0;">
          Valuation Overlay
      </p>
      <p style="font-size: 0.95rem; color: #333333; margin: 0;">
          DCF (FCFF) · Residual Income · Total Payout — consensus fair value per holding
      </p>
    </div>
  </div>

  <hr style="border: none; border-top: 1px solid #E0E0E0; margin: 1rem 0;" />

  <div style="display: flex; gap: 3rem; flex-wrap: wrap;">
    <div>
      <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.08em; color: #666666; margin: 0 0 0.3rem 0;">
          Core Thesis
      </p>
      <p style="font-size: 0.88rem; color: #333333; line-height: 1.65; margin: 0; max-width: 420px;">
          Markets systematically misprice companies undergoing operational transitions,
          sector rotations, or short-term earnings pressure. Shepherd Capital targets
          this gap — owning quality businesses when sentiment is weakest and the
          risk/reward asymmetry is most favourable.
      </p>
    </div>
    <div>
      <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.08em; color: #666666; margin: 0 0 0.3rem 0;">
          Risk Management
      </p>
      <p style="font-size: 0.88rem; color: #333333; line-height: 1.65; margin: 0; max-width: 380px;">
          Position sizing is equal-weighted to prevent concentration risk. Stale
          recommendations (18+ months without reaffirmation) are automatically flagged
          for review. Hard valuation stops are enforced where the fair-value consensus
          is unavailable or confidence is low.
      </p>
    </div>
  </div>

  <hr style="border: none; border-top: 1px solid #E0E0E0; margin: 1rem 0;" />

  <div style="display: flex; align-items: center; gap: 1.6rem; flex-wrap: wrap;">
    <p style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
              letter-spacing: 0.08em; color: #666666; margin: 0;">
        Research
    </p>
<a href="{_sub_url}" target="_blank" style="
        font-size: 0.88rem; font-weight: 600; color: #1E3DA5;
        text-decoration: none; border-bottom: 1px solid rgba(30,61,165,0.3);
        padding-bottom: 1px; transition: border-color 0.15s;">
        Substack Newsletter ↗
    </a>
  </div>
</div>
""", unsafe_allow_html=True)

    # KPI row
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Scraped Articles", len(sources))
    with col2:
        st.metric("Extracted Ideas", len(recs))
    with col3:
        active_h = holdings[holdings["active_status"] == 1] if not holdings.empty and "active_status" in holdings.columns else holdings
        st.metric("Active Holdings", len(active_h))

    initial = get_config_value("portfolio", "initial_capital", default=100_000)
    with col4:
        if not perf.empty and "fund_value" in perf.columns:
            current_val = float(perf.sort_values("date").iloc[-1]["fund_value"])
            st.metric("Fund Value", f"{current_val:,.0f}", delta=f"{(current_val - initial) / initial * 100:.2f}%")
        else:
            st.metric("Fund Value", "—")
    with col5:
        if not perf.empty and "fund_value" in perf.columns:
            total_ret = (float(perf.sort_values("date").iloc[-1]["fund_value"]) - initial) / initial * 100
            st.metric("Total Return", f"{total_ret:.2f}%")
        else:
            st.metric("Total Return", "—")

    st.markdown("---")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Top & Bottom Performers")
        if not holdings.empty and "total_return" in holdings.columns:
            disp = holdings[["ticker", "company_name", "total_return", "current_price"]].copy()
            disp["total_return_pct"] = disp["total_return"].apply(
                lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—"
            )
            st.dataframe(
                disp.sort_values("total_return", ascending=False)[
                    ["ticker", "company_name", "total_return_pct", "current_price"]
                ].rename(columns={"total_return_pct": "Return"}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No holdings yet. Run the pipeline to populate.")

    with col_b:
        st.subheader("Recommendation Distribution")
        if not recs.empty and "recommendation_type" in recs.columns:
            counts = recs["recommendation_type"].value_counts().reset_index()
            counts.columns = ["Type", "Count"]
            fig = px.pie(counts, names="Type", values="Count", hole=0.4,
                         color_discrete_sequence=_SPX_COLORS)
            fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10),
                              paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No recommendations extracted yet.")

    st.markdown("---")
    last_scrape = sources["fetched_at"].max() if not sources.empty and "fetched_at" in sources.columns else None
    st.caption(f"Last data refresh: {last_scrape or 'Never'}")


def page_fund_performance():
    st.title("Fund Performance")
    data = get_data()
    perf = data["perf"]

    if perf.empty or "fund_value" not in perf.columns:
        st.info("No performance data yet. Run: `python -m src.main build-portfolio`")
        return

    perf = perf.sort_values("date").copy()
    perf["date"] = pd.to_datetime(perf["date"])

    # Line chart
    st.subheader("Fund Value vs Benchmarks")
    fig = go.Figure()
    initial = get_config_value("portfolio", "initial_capital", default=100_000)

    fig.add_trace(go.Scatter(
        x=perf["date"], y=perf["fund_value"],
        name="Shepherd Capital Fund", line=dict(color="#1E3DA5", width=2.5)
    ))
    for col, name, color in [
        ("benchmark_spy", "SPY", "#F5A623"),
        ("benchmark_qqq", "QQQ", "#00A878"),
        ("benchmark_world", "URTH", "#666666"),
    ]:
        if col in perf.columns and perf[col].notna().any():
            fig.add_trace(go.Scatter(
                x=perf["date"], y=perf[col],
                name=name, line=dict(dash="dash", width=1.5, color=color), opacity=0.85
            ))

    fig.update_layout(
        **_spx_layout(
            yaxis_title="Value (currency units)",
            xaxis_title="Date",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=450,
        )
    )
    st.plotly_chart(fig, use_container_width=True)

    # Drawdown chart
    st.subheader("Drawdown")
    perf["rolling_max"] = perf["fund_value"].cummax()
    perf["drawdown"] = (perf["fund_value"] - perf["rolling_max"]) / perf["rolling_max"] * 100
    fig_dd = px.area(perf, x="date", y="drawdown", color_discrete_sequence=["#D93025"])
    fig_dd.update_layout(**_spx_layout(yaxis_title="Drawdown (%)", height=250))
    st.plotly_chart(fig_dd, use_container_width=True)

    # Monthly returns table
    st.subheader("Monthly Returns")
    if "daily_return" in perf.columns:
        perf["month"] = perf["date"].dt.to_period("M")
        monthly = perf.groupby("month").agg(
            fund_return=("fund_value", lambda x: (x.iloc[-1] / x.iloc[0] - 1) * 100 if len(x) > 1 else 0)
        ).reset_index()
        monthly["month"] = monthly["month"].astype(str)
        monthly["fund_return"] = monthly["fund_return"].round(2)
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    # Summary stats
    st.subheader("Statistics")
    total_ret = (perf["fund_value"].iloc[-1] / perf["fund_value"].iloc[0] - 1) * 100
    max_dd = perf["drawdown"].min()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Return", f"{total_ret:.2f}%")
    col2.metric("Max Drawdown", f"{max_dd:.2f}%")
    if "daily_return" in perf.columns:
        ann_vol = perf["daily_return"].std() * (252 ** 0.5) * 100
        col3.metric("Annualised Volatility", f"{ann_vol:.2f}%")


def page_holdings():
    st.title("Holdings")
    data = get_data()
    holdings = data["holdings"]

    if holdings.empty:
        st.info("No holdings built yet. Run: `python -m src.main build-portfolio`")
        return

    recs = data["recs"]

    # Enrich with recommendation count
    if not recs.empty and "ticker" in recs.columns:
        rec_counts = recs.groupby("ticker").size().reset_index(name="rec_count")
        holdings = holdings.merge(rec_counts, on="ticker", how="left")

    cols = [
        "ticker", "company_name", "weight", "entry_date",
        "entry_price", "current_price", "total_return",
        "market_value", "shares",
    ]
    if "rec_count" in holdings.columns:
        cols.append("rec_count")

    available = [c for c in cols if c in holdings.columns]
    df = holdings[available].copy()

    if "weight" in df.columns:
        df["weight"] = df["weight"].apply(lambda x: round(x * 100, 2) if pd.notna(x) else None)
    if "total_return" in df.columns:
        df["total_return_pct"] = df["total_return"].apply(
            lambda x: round(x * 100, 2) if pd.notna(x) else None
        )

    st.dataframe(
        df.sort_values("total_return", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "weight": st.column_config.NumberColumn("Weight %", format="%.1f%%"),
            "total_return_pct": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            "entry_price": st.column_config.NumberColumn("Entry Price", format="%.2f"),
            "current_price": st.column_config.NumberColumn("Current Price", format="%.2f"),
            "market_value": st.column_config.NumberColumn("Market Value", format="%.0f"),
        }
    )



def page_recommendations():
    st.title("Recommendation Explorer")
    data = get_data()
    recs = data["recs"]
    sources = data["sources"]

    if recs.empty:
        st.info("No recommendations extracted yet. Run: `python -m src.main extract`")
        return

    # Merge source URL
    if not sources.empty and "id" in sources.columns and "source_id" in recs.columns:
        recs = recs.merge(
            sources[["id", "url", "title"]].rename(columns={"id": "source_id", "url": "source_url", "title": "source_title"}),
            on="source_id",
            how="left",
        )

    st.subheader("Filters")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        ticker_filter = st.text_input("Ticker", "")
    with col2:
        rec_types = ["All"] + sorted(recs["recommendation_type"].dropna().unique().tolist())
        rec_type_filter = st.selectbox("Recommendation type", rec_types)
    with col3:
        conf_levels = ["All"] + sorted(recs["confidence"].dropna().unique().tolist())
        conf_filter = st.selectbox("Confidence", conf_levels)
    with col4:
        if "recommendation_date" in recs.columns:
            recs["recommendation_date"] = pd.to_datetime(recs["recommendation_date"], errors="coerce")
            min_date = recs["recommendation_date"].min()
            max_date = recs["recommendation_date"].max()
            if pd.notna(min_date) and pd.notna(max_date):
                date_range = st.date_input(
                    "Date range",
                    value=(min_date.date(), max_date.date()),
                )
            else:
                date_range = None
        else:
            date_range = None

    filtered = recs.copy()
    if ticker_filter:
        filtered = filtered[filtered["ticker"].str.contains(ticker_filter.upper(), na=False)]
    if rec_type_filter != "All":
        filtered = filtered[filtered["recommendation_type"] == rec_type_filter]
    if conf_filter != "All":
        filtered = filtered[filtered["confidence"] == conf_filter]
    if date_range and len(date_range) == 2 and "recommendation_date" in filtered.columns:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        filtered = filtered[
            filtered["recommendation_date"].between(start, end, inclusive="both")
        ]

    st.write(f"Showing {len(filtered)} of {len(recs)} recommendations")

    display_cols = [
        "ticker", "company_name", "recommendation_type", "confidence",
        "recommendation_date", "thesis_summary", "catalysts", "risks",
        "target_price", "time_horizon",
    ]
    if "source_url" in filtered.columns:
        display_cols.append("source_url")

    available = [c for c in display_cols if c in filtered.columns]
    st.dataframe(
        filtered[available].sort_values("recommendation_date", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "source_url": st.column_config.LinkColumn("Source"),
            "thesis_summary": st.column_config.TextColumn("Thesis", width="large"),
        }
    )


def page_sources():
    st.title("Source Articles")
    data = get_data()
    sources = data["sources"]
    recs = data["recs"]

    if sources.empty:
        st.info("No sources scraped yet. Run: `python -m src.main scrape`")
        return

    # Ticker extraction count per source
    if not recs.empty and "source_id" in recs.columns:
        ticker_counts = recs.groupby("source_id")["ticker"].apply(
            lambda x: ", ".join(x.dropna().unique()[:5])
        ).reset_index(name="extracted_tickers")
        sources = sources.merge(ticker_counts, left_on="id", right_on="source_id", how="left")

    cols = ["source_type", "title", "author", "published_date", "url", "status", "extracted_tickers"]
    available = [c for c in cols if c in sources.columns]

    status_filter = st.selectbox("Filter by status", ["All"] + sources["status"].dropna().unique().tolist())
    type_filter = st.selectbox("Filter by type", ["All"] + sources["source_type"].dropna().unique().tolist())

    filtered = sources.copy()
    if status_filter != "All":
        filtered = filtered[filtered["status"] == status_filter]
    if type_filter != "All":
        filtered = filtered[filtered["source_type"] == type_filter]

    st.write(f"Showing {len(filtered)} sources")
    st.dataframe(
        filtered[available].sort_values("published_date", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("URL")},
    )


def page_manual_review():
    st.title("Manual Review")
    data = get_data()
    ticker_map = data["ticker_map"]
    recs = data["recs"]

    st.subheader("Low Confidence Ticker Mappings")
    st.caption("These tickers could not be resolved with high confidence. Export to CSV to manually correct.")

    if not ticker_map.empty and "confidence" in ticker_map.columns:
        low = ticker_map[ticker_map["confidence"] < 0.7].copy()
        st.write(f"{len(low)} ambiguous mappings")
        st.dataframe(low, use_container_width=True, hide_index=True)

        csv = low.to_csv(index=False)
        st.download_button(
            "Download for manual correction",
            csv,
            file_name="ambiguous_tickers.csv",
            mime="text/csv",
        )
    else:
        st.info("No ticker mappings yet.")

    st.markdown("---")
    st.subheader("Low Confidence Extractions")

    if not recs.empty and "extraction_confidence" in recs.columns:
        low_recs = recs[recs["extraction_confidence"] < 0.5]
        st.write(f"{len(low_recs)} low-confidence extractions")
        cols = ["ticker", "company_name", "recommendation_type", "confidence",
                "extraction_method", "extraction_confidence", "excerpt"]
        available = [c for c in cols if c in low_recs.columns]
        st.dataframe(low_recs[available], use_container_width=True, hide_index=True)
    else:
        st.info("No extractions yet.")

    st.markdown("---")
    st.subheader("New Since Last Run")
    if not recs.empty and "created_at" in recs.columns:
        recs["created_at"] = pd.to_datetime(recs["created_at"], errors="coerce")
        cutoff = recs["created_at"].max() - pd.Timedelta(hours=24)
        new = recs[recs["created_at"] >= cutoff]
        st.write(f"{len(new)} new extractions in last 24h")
        if not new.empty:
            cols = ["ticker", "company_name", "recommendation_type", "confidence", "created_at"]
            available = [c for c in cols if c in new.columns]
            st.dataframe(new[available], use_container_width=True, hide_index=True)


def page_refresh():
    st.title("Refresh & Export")

    st.subheader("Pipeline Controls")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Scrape New Content", use_container_width=True):
            run_step("Scrape", lambda: (
                __import__("src.scrape_substack", fromlist=["scrape_substack"]).scrape_substack(),
                __import__("src.scrape_website", fromlist=["scrape_website"]).scrape_website(),
            ))

        if st.button("Extract Recommendations", use_container_width=True):
            run_step("Extract", lambda: __import__("src.extract_recommendations", fromlist=["extract_all"]).extract_all())

        if st.button("Resolve Tickers", use_container_width=True):
            run_step("Resolve Tickers", lambda: (
                __import__("src.ticker_resolver", fromlist=["resolve_tickers"]).resolve_tickers(),
                __import__("src.ticker_resolver", fromlist=["enrich_recommendations_with_tickers"]).enrich_recommendations_with_tickers(),
            ))

    with col2:
        if st.button("Refresh Prices", use_container_width=True):
            run_step("Refresh Prices", lambda: __import__("src.price_fetcher", fromlist=["refresh_all_tracked_prices"]).refresh_all_tracked_prices())

        if st.button("Rebuild Portfolio", use_container_width=True):
            run_step("Build Portfolio", lambda: (
                __import__("src.portfolio_builder", fromlist=["build_portfolio"]).build_portfolio(),
                __import__("src.portfolio_builder", fromlist=["build_performance_history"]).build_performance_history(),
            ))

        if st.button("Export Excel", use_container_width=True):
            run_step("Export Excel", lambda: __import__("src.export_excel", fromlist=["export_excel"]).export_excel())
            exports_dir = get_config_value("output", "exports_dir", default="data/exports")
            st.info(f"Excel saved to: {exports_dir}/")

    st.markdown("---")
    st.subheader("Run Full Pipeline")
    if st.button("Run All Steps", type="primary", use_container_width=True):
        steps = [
            ("Scrape", lambda: (
                __import__("src.scrape_substack", fromlist=["scrape_substack"]).scrape_substack(),
                __import__("src.scrape_website", fromlist=["scrape_website"]).scrape_website(),
            )),
            ("Extract", lambda: __import__("src.extract_recommendations", fromlist=["extract_all"]).extract_all()),
            ("Resolve Tickers", lambda: (
                __import__("src.ticker_resolver", fromlist=["resolve_tickers"]).resolve_tickers(),
                __import__("src.ticker_resolver", fromlist=["enrich_recommendations_with_tickers"]).enrich_recommendations_with_tickers(),
            )),
            ("Refresh Prices", lambda: __import__("src.price_fetcher", fromlist=["refresh_all_tracked_prices"]).refresh_all_tracked_prices()),
            ("Build Portfolio", lambda: (
                __import__("src.portfolio_builder", fromlist=["build_portfolio"]).build_portfolio(),
                __import__("src.portfolio_builder", fromlist=["build_performance_history"]).build_performance_history(),
            )),
            ("Export Excel", lambda: __import__("src.export_excel", fromlist=["export_excel"]).export_excel()),
        ]
        for name, fn in steps:
            run_step(name, fn)
        st.balloons()

    st.markdown("---")
    st.subheader("Download Data")
    data = get_data()
    for key, label in [
        ("holdings", "Holdings"),
        ("recs", "Recommendations"),
        ("sources", "Source Articles"),
        ("ticker_map", "Ticker Map"),
    ]:
        df = data[key]
        if not df.empty:
            csv = df.to_csv(index=False)
            st.download_button(
                f"Download {label} CSV",
                csv,
                file_name=f"{key}.csv",
                mime="text/csv",
            )


# ---------------------------------------------------------------------------
# Fair Value Analysis
# ---------------------------------------------------------------------------

_RATING_COLOUR = {"BUY": "", "HOLD": "", "SELL": "", "N/A": ""}
_CONFIDENCE_COLOUR = {"high": "", "medium": "", "low": ""}


def _run_single_valuation(ticker: str):
    """Import and run valuation for one ticker; returns result or None."""
    try:
        from src.equity_analyser.runner import run_valuation
        return run_valuation(ticker)
    except Exception as exc:
        return exc  # surface the error in the cache


def page_fair_value():
    st.title("Fair Value Analysis")
    st.markdown(
        "Multi-model intrinsic valuation (DCF · Residual Income · Total Payout) "
        "run against each portfolio holding. Ratings reflect **conservative fundamental value** — "
        "growth stocks typically trade at premiums to intrinsic value, so a SELL rating means "
        "'significant growth premium priced in', not necessarily a recommendation to sell."
    )
    st.markdown("---")

    data = get_data()
    holdings = data["holdings"]

    if holdings.empty:
        st.info("No holdings found. Run `build-portfolio` first.")
        return

    active = (
        holdings[holdings["active_status"] == 1]
        if "active_status" in holdings.columns else holdings
    )
    tickers = sorted(active["ticker"].dropna().unique().tolist())

    # Session-state cache for valuation results
    if "fv_results" not in st.session_state:
        st.session_state["fv_results"] = {}
    cache: dict = st.session_state["fv_results"]

    # Controls
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([3, 2, 2, 2])
    with ctrl1:
        run_all = st.button("▶ Run All Valuations", type="primary",
                            help="Fetches live financials from yfinance — takes 2-3 min for full portfolio")
    with ctrl2:
        ticker_single = st.selectbox("Run single ticker", ["— select —"] + tickers,
                                     label_visibility="collapsed")
        run_one = st.button("Run Selected")
    with ctrl3:
        if st.button("Clear Cache"):
            st.session_state["fv_results"] = {}
            st.rerun()
    with ctrl4:
        valued = sum(1 for v in cache.values() if not isinstance(v, Exception))
        st.metric("Valued", f"{valued} / {len(tickers)}")

    # --- Execute valuations ---
    if run_all:
        prog = st.progress(0, text="Starting…")
        status = st.empty()
        for i, t in enumerate(tickers):
            status.text(f"Valuing {t}  ({i + 1}/{len(tickers)})…")
            cache[t] = _run_single_valuation(t)
            prog.progress((i + 1) / len(tickers),
                          text=f"Valuing {t} ({i + 1}/{len(tickers)})")
        prog.empty()
        status.empty()
        st.success(f"Done — {valued + 1} tickers valued.")
        st.rerun()

    if run_one and ticker_single != "— select —":
        with st.spinner(f"Valuing {ticker_single}…"):
            cache[ticker_single] = _run_single_valuation(ticker_single)
        st.rerun()

    if not cache:
        st.info("Click **▶ Run All Valuations** to generate fair value estimates.")
        return

    # --- Build summary table ---
    rows = []
    for t in tickers:
        result = cache.get(t)
        h_row = active[active["ticker"] == t]
        current_price = float(h_row["current_price"].iloc[0]) if not h_row.empty and "current_price" in h_row.columns else None

        if result is None or isinstance(result, Exception):
            error_msg = str(result) if isinstance(result, Exception) else "Not run"
            rows.append(dict(
                ticker=t, company=t, current_price=current_price,
                fair_value=None, fv_low=None, fv_high=None,
                upside_pct=None, rating="N/A", confidence="—",
                growth_premium=None, models_used="—", error=error_msg,
            ))
            continue

        v = result.verdict
        c = result.consensus

        if v is None or c is None:
            rows.append(dict(
                ticker=t,
                company=result.company.name if result else t,
                current_price=current_price,
                fair_value=None, fv_low=None, fv_high=None,
                upside_pct=None, rating="N/A",
                confidence=result.confidence if result else "—",
                growth_premium=None,
                models_used=", ".join(c.component_values.keys()) if c else "insufficient data",
                error="Insufficient data for consensus",
            ))
            continue

        rating_map = {"undervalued": "BUY", "fairly_valued": "HOLD", "overvalued": "SELL"}
        rating = rating_map.get(v.label, "N/A")
        premium = (v.current_price / v.fair_value_mid - 1) if v.fair_value_mid > 0 else None

        rows.append(dict(
            ticker=t,
            company=result.company.name,
            current_price=round(v.current_price, 2),
            fair_value=round(v.fair_value_mid, 2),
            fv_low=round(v.fair_value_low, 2),
            fv_high=round(v.fair_value_high, 2),
            upside_pct=round(v.upside_downside_pct * 100, 1),
            rating=rating,
            confidence=result.confidence,
            growth_premium=round(premium * 100, 1) if premium is not None else None,
            models_used=", ".join(c.component_values.keys()),
            error="",
        ))

    df = pd.DataFrame(rows)
    valued_df = df[df["fair_value"].notna()].copy()

    # --- Summary KPIs ---
    if not valued_df.empty:
        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.metric("BUY", int((valued_df["rating"] == "BUY").sum()))
        kc2.metric("HOLD", int((valued_df["rating"] == "HOLD").sum()))
        kc3.metric("SELL", int((valued_df["rating"] == "SELL").sum()))
        kc4.metric("Avg Growth Premium",
                   f"{valued_df['growth_premium'].mean():.0f}%"
                   if valued_df["growth_premium"].notna().any() else "—")

    st.markdown("---")

    # --- Main results table ---
    st.subheader("Valuation Results")

    display_cols = ["ticker", "company", "current_price", "fair_value",
                    "fv_low", "fv_high", "upside_pct", "growth_premium",
                    "rating", "confidence", "models_used"]
    disp = df[[c for c in display_cols if c in df.columns]].copy()

    def rating_icon(r):
        return str(r)

    def conf_icon(c):
        return str(c)

    if "rating" in disp.columns:
        disp["rating"] = disp["rating"].apply(rating_icon)
    if "confidence" in disp.columns:
        disp["confidence"] = disp["confidence"].apply(conf_icon)

    st.dataframe(
        disp.sort_values("upside_pct", ascending=False, na_position="last"),
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", width="small"),
            "company": st.column_config.TextColumn("Company"),
            "current_price": st.column_config.NumberColumn("Market Price", format="$%.2f"),
            "fair_value": st.column_config.NumberColumn("Fair Value (Mid)", format="$%.2f"),
            "fv_low": st.column_config.NumberColumn("FV Low", format="$%.2f"),
            "fv_high": st.column_config.NumberColumn("FV High", format="$%.2f"),
            "upside_pct": st.column_config.NumberColumn("Upside %", format="%.1f%%"),
            "growth_premium": st.column_config.NumberColumn("Growth Premium %", format="%.0f%%",
                help="How far above intrinsic value the market price is. Positive = priced above FV."),
            "rating": st.column_config.TextColumn("Rating"),
            "confidence": st.column_config.TextColumn("Confidence"),
            "models_used": st.column_config.TextColumn("Models"),
        },
    )

    # --- Upside waterfall chart ---
    if not valued_df.empty:
        st.markdown("---")
        st.subheader("Upside / Downside to Fair Value")
        chart_df = valued_df.sort_values("upside_pct", ascending=True).head(40)
        colours = chart_df["upside_pct"].apply(
            lambda x: "#00A878" if x > 0 else "#D93025"
        ).tolist()
        fig = go.Figure(go.Bar(
            x=chart_df["upside_pct"],
            y=chart_df["ticker"],
            orientation="h",
            marker_color=colours,
            text=chart_df["upside_pct"].apply(lambda x: f"{x:+.1f}%"),
            textposition="outside",
        ))
        fig.update_layout(
            **_spx_layout(
                height=max(400, len(chart_df) * 22),
                xaxis_title="Upside to Fair Value (%)",
                xaxis=dict(zeroline=True, zerolinewidth=2, zerolinecolor="#E0E0E0",
                           gridcolor="#EEEEEE"),
                margin=dict(l=20, r=60, t=20, b=40),
            )
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- Per-ticker drill-down ---
    st.markdown("---")
    st.subheader("Model Breakdown by Ticker")
    sel_ticker = st.selectbox("Select ticker for detail", ["— select —"] + tickers, key="fv_drill")

    if sel_ticker != "— select —" and sel_ticker in cache:
        result = cache[sel_ticker]
        if isinstance(result, Exception):
            st.error(f"Valuation failed: {result}")
        elif result is None:
            st.warning("No data returned for this ticker.")
        else:
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown(f"**{result.company.name}** ({sel_ticker})")
                st.markdown(f"Sector: {result.company.sector or '—'} | "
                            f"Industry: {result.company.industry or '—'}")
                st.markdown(f"Confidence: **{result.confidence.upper()}**  "
                            f"| Standard: {result.company.accounting_standard.value.upper()}")
                if result.data_quality_flags:
                    with st.expander("Data quality flags"):
                        for f in result.data_quality_flags:
                            st.markdown(f"- {f}")

            with col_b:
                if result.verdict:
                    v = result.verdict
                    st.metric("Market Price", f"${v.current_price:.2f}")
                    st.metric("Fair Value (Mid)", f"${v.fair_value_mid:.2f}",
                              delta=f"{v.upside_downside_pct:+.1%} upside")
                    st.caption(f"Range: ${v.fair_value_low:.2f} – ${v.fair_value_high:.2f}")
                    st.markdown(f"**{rating_map.get(v.label, 'N/A')}**")
                    st.caption(v.rationale)

            # Model details
            model_rows = []
            if result.dcf_fcff:
                d = result.dcf_fcff
                model_rows.append({
                    "Model": "DCF (FCFF)",
                    "Fair Value": f"${d.equity_value_per_share:.2f}",
                    "Key Assumption": f"Ke={d.cost_of_equity:.1%}, g={d.terminal_growth:.1%}",
                    "Notes": " | ".join(d.notes[:2]),
                })
            if result.residual_income:
                ri = result.residual_income
                model_rows.append({
                    "Model": "Residual Income",
                    "Fair Value": f"${ri.equity_value_per_share:.2f}",
                    "Key Assumption": f"Ke={ri.cost_of_equity:.1%}, opening BVps=${ri.opening_book_value_per_share:.2f}",
                    "Notes": " | ".join(ri.notes[:2]),
                })
            if result.total_payout:
                p = result.total_payout
                model_rows.append({
                    "Model": "Total Payout",
                    "Fair Value": f"${p.equity_value_per_share:.2f}",
                    "Key Assumption": f"Ke={p.cost_of_equity:.1%}, g_terminal={p.terminal_growth:.1%}",
                    "Notes": " | ".join(p.notes[:2]),
                })

            if model_rows:
                st.dataframe(pd.DataFrame(model_rows), use_container_width=True, hide_index=True)

            # DCF sensitivity
            if result.dcf_fcff and result.dcf_fcff.sensitivity:
                with st.expander("DCF Sensitivity Grid (equity value per share)"):
                    sg = result.dcf_fcff.sensitivity
                    sens_data = {}
                    for i, ke_v in enumerate(sg.row_values):
                        row_data = {}
                        for j, g_v in enumerate(sg.col_values):
                            val = sg.grid[i][j]
                            row_data[f"g={g_v:.1%}"] = f"${val:.0f}" if not pd.isna(val) else "—"
                        sens_data[f"Ke={ke_v:.1%}"] = row_data
                    sens_df = pd.DataFrame(sens_data).T
                    st.dataframe(sens_df, use_container_width=True)

            if result.company.description:
                with st.expander("Business Description"):
                    st.markdown(result.company.description)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if page == "Overview":
    page_overview()
elif page == "Fund Performance":
    page_fund_performance()
elif page == "Holdings":
    page_holdings()
elif page == "Recommendation Explorer":
    page_recommendations()
elif page == "Source Articles":
    page_sources()
elif page == "Manual Review":
    page_manual_review()
elif page == "Refresh & Export":
    page_refresh()
elif page == "Fair Value Analysis":
    page_fair_value()
