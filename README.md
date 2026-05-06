# Rebound Capital — Synthetic Fund Tracker

A local-first Python system for collecting, structuring, and tracking investment ideas from Rebound Capital's public content.

---

## Compliance Notice

This tool:
- Collects **only publicly available** content (no paywall bypass, no login walls)
- Respects `robots.txt` on all domains
- Applies reasonable request delays between fetches
- Caches raw HTML locally to avoid repeated requests
- Does **not** reproduce full article text — only metadata, short excerpts, ticker symbols, and summaries
- Is intended for **personal research only** — not redistribution or commercial use

---

## Project Structure

```
rebound_capital_tracker/
├── config.yaml               ← All configuration (edit this first)
├── requirements.txt
├── .env.example              ← Copy to .env for optional LLM keys
├── data/
│   ├── raw_html/             ← Cached HTML pages
│   ├── processed/
│   │   └── manual_ticker_overrides.csv
│   ├── exports/              ← Excel output
│   └── rebound_tracker.sqlite
├── src/
│   ├── main.py               ← CLI entry point
│   ├── database.py           ← SQLAlchemy models
│   ├── utils.py              ← Shared utilities
│   ├── scrape_substack.py    ← Substack scraper
│   ├── scrape_website.py     ← Website scraper
│   ├── extract_recommendations.py  ← NLP + regex extraction
│   ├── ticker_resolver.py    ← Ticker resolution
│   ├── price_fetcher.py      ← yfinance price data
│   ├── portfolio_builder.py  ← Synthetic fund construction
│   └── export_excel.py       ← Excel workbook export
├── dashboard/
│   └── app.py                ← Streamlit dashboard
└── tests/
    └── test_extraction.py
```

---

## Installation

### 1. Prerequisites

- Python 3.10 or later
- pip

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate      # macOS/Linux
venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Optional: configure LLM-assisted extraction

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY or OPENAI_API_KEY
```

---

## Configuration

Open `config.yaml` and set the source URLs:

```yaml
sources:
  substack_url: "https://reboundcapital.substack.com"   # ← insert actual URL
  website_url:  "https://www.reboundcapital.com"         # ← insert actual URL
```

All other settings have sensible defaults. Key options:

| Setting | Default | Description |
|---|---|---|
| `scraping.request_delay_seconds` | 2.0 | Seconds between requests |
| `scraping.max_pages` | 500 | Max pages per scraper run |
| `portfolio.weighting` | `equal` | `equal` / `recency` / `confidence` / `frequency` |
| `portfolio.initial_capital` | 100000 | Starting fund value |
| `portfolio.rebalance_frequency` | `monthly` | `monthly` / `quarterly` / `never` |
| `extraction.use_llm` | `false` | Enable LLM extraction (requires API key) |
| `extraction.stale_months` | 18 | Months without mention before marking stale |

---

## Running the Pipeline

### Full pipeline (recommended for first run)

```bash
cd rebound_capital_tracker
python -m src.main run-all
```

### Individual steps

```bash
# 1. Scrape new content
python -m src.main scrape

# 2. Extract investment ideas
python -m src.main extract

# 3. Resolve company names to canonical tickers
python -m src.main resolve-tickers

# 4. Refresh stock prices
python -m src.main refresh-prices

# 5. Build synthetic fund portfolio
python -m src.main build-portfolio

# 6. Export to Excel
python -m src.main export-excel
```

### Force-refresh options

```bash
python -m src.main scrape --force           # re-fetch already cached pages
python -m src.main refresh-prices --force   # bypass price cache
python -m src.main run-all --force-scrape --force-prices
```

---

## Launching the Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at `http://localhost:8501`

Dashboard sections:
- **Overview** — KPIs, recommendation distribution
- **Fund Performance** — value chart, drawdown, monthly returns vs benchmarks
- **Holdings** — interactive table with weights and returns
- **Recommendation Explorer** — searchable/filterable ideas table
- **Source Articles** — scraped pages with status
- **Manual Review** — ambiguous tickers and low-confidence extractions
- **Refresh & Export** — pipeline controls, CSV/Excel download buttons

---

## Exporting to Excel

```bash
python -m src.main export-excel
```

Output: `data/exports/rebound_capital_fund_tracker.xlsx`

Tabs:
1. **Summary** — KPIs, methodology, compliance note
2. **Holdings** — current fund positions with P&L
3. **Recommendations** — all extracted ideas
4. **Source Articles** — scraped pages
5. **Price History** — historical OHLCV
6. **Fund Performance** — daily fund value vs benchmarks
7. **Manual Review** — ambiguous mappings for correction

---

## Portfolio Methodology

1. **Candidate selection** — Only `buy`, `long`, `add`, `portfolio_holding`, and high-confidence `watchlist` recommendations are included. `sell`, `short`, `avoid`, `trim`, and `mention_only` are excluded.

2. **Stale filtering** — Any recommendation with no positive mention in >18 months is excluded unless explicitly labelled as a `portfolio_holding`.

3. **Deduplication** — If a ticker appears multiple times, the earliest buy/long date is used as the entry date, and later articles update the thesis.

4. **Weighting** — Equal weight by default. Alternatives: recency-weighted, confidence-weighted, frequency-weighted.

5. **Entry price** — Closing price on or nearest to the first positive recommendation date.

6. **Rebalancing** — Monthly by default (equal weight re-applied).

7. **Benchmark** — SPY, QQQ, and URTH (MSCI World proxy) — normalised to initial capital.

**Limitation**: This is a backtest-style reconstruction, not real trading. No transaction costs, slippage, or taxes are modelled.

---

## Manually Correcting Ticker Mappings

1. Open `data/processed/manual_ticker_overrides.csv`
2. Add or edit rows:

```csv
company_name,ticker,exchange,notes
Prosus NV,PRX,EURONEXT,Amsterdam-listed
Naspers Limited,NPN,JSE,
```

3. Re-run ticker resolution:

```bash
python -m src.main resolve-tickers
```

Manual overrides always take priority over automated lookups.

---

## LLM-Assisted Extraction

If you have an Anthropic or OpenAI API key, set it in `.env` and enable in `config.yaml`:

```yaml
extraction:
  use_llm: true
  llm_provider: "anthropic"   # or "openai"
```

LLM extraction produces richer thesis summaries and better recommendation classification, especially for nuanced or implicit language. The system falls back to regex extraction if no key is present or the API call fails.

**LLM used**: `claude-haiku-4-5-20251001` (Anthropic) or `gpt-4o-mini` (OpenAI) — fast, low-cost models suitable for structured extraction.

---

## Running Tests

```bash
pytest tests/ -v
```

Tests cover:
- Ticker extraction and false-positive filtering
- Recommendation classification
- URL normalisation and deduplication
- Portfolio weighting logic (all four methods)
- Metadata extraction (price targets, time horizons, catalysts, risks)

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Run from the `rebound_capital_tracker/` directory; ensure venv is active |
| No articles found | Check that Substack/website URLs are set in `config.yaml` |
| `robots.txt disallows` warning | The scraper correctly skips disallowed pages — this is expected |
| No price data | Verify tickers are correctly resolved; check `ticker_map` table |
| LLM extraction fails | Check API key in `.env`; system falls back to regex automatically |
| Empty portfolio | Ensure extraction ran and produced `buy`/`long`/`add`/`portfolio_holding` recommendations |
| Excel file locked | Close the previous Excel file before re-exporting |

---

## Limitations

- **Regex-based extraction** can misidentify tickers, especially short 2-3 letter sequences in non-financial contexts. Use the Manual Review page to correct these.
- **Historical entry prices** rely on yfinance data availability. Very old recommendations or delisted tickers may have no price data.
- **Substack paywall** — Only free/public articles are fetched. Paid subscriber content is not accessible and is correctly skipped.
- **No transaction costs** — The synthetic fund does not model commissions, spreads, or taxes.
- **Thesis summaries** are extracted from public text — the system does not invent analysis.
- **Stale detection** is heuristic — a stock may still be held even if not recently mentioned.

---

## Suggested Next Improvements

1. Add sector allocation using `yfinance` info API
2. Add geographic allocation chart (inferred from exchange)
3. Dividend-adjusted return tracking
4. Currency conversion for non-USD holdings
5. Email/notification summary for new recommendations
6. "Recommendation timeline per stock" chart in dashboard
7. More sophisticated NLP (SpaCy entity recognition for company names)
8. Scheduled automatic refresh (cron job or Streamlit Cloud)
9. Support for Twitter/X or other public social sources
10. Integration with brokerage API for live portfolio comparison
