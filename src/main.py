"""
Rebound Capital Tracker — CLI entry point.

Usage:
  python -m src.main scrape
  python -m src.main extract
  python -m src.main resolve-tickers
  python -m src.main refresh-prices
  python -m src.main build-portfolio
  python -m src.main export-excel
  python -m src.main run-all
"""
from __future__ import annotations

import sys
import time

import click

from src.utils import get_logger

logger = get_logger("main")


def _init() -> None:
    from src.database import init_db
    init_db()


@click.group()
def cli():
    """Rebound Capital synthetic fund tracker."""
    pass


@cli.command()
@click.option("--force", is_flag=True, help="Re-fetch already scraped URLs")
def scrape(force: bool) -> None:
    """Scrape Substack and official website."""
    _init()
    click.echo("=== Scraping Substack ===")
    from src.scrape_substack import scrape_substack
    n1 = scrape_substack(force_refresh=force)
    click.echo(f"Substack: {n1} new articles fetched")

    click.echo("=== Scraping Website ===")
    from src.scrape_website import scrape_website
    n2 = scrape_website(force_refresh=force)
    click.echo(f"Website: {n2} new pages fetched")

    click.echo(f"Scrape complete. Total new: {n1 + n2}")


@cli.command()
@click.option("--force", is_flag=True, help="Re-extract from already-processed sources")
def extract(force: bool) -> None:
    """Extract stock recommendations from scraped content."""
    _init()
    click.echo("=== Extracting recommendations ===")
    from src.extract_recommendations import extract_all
    n = extract_all(force_reextract=force)
    click.echo(f"Extracted {n} investment ideas")


@cli.command("resolve-tickers")
def resolve_tickers() -> None:
    """Resolve company names to canonical tickers."""
    _init()
    click.echo("=== Resolving tickers ===")
    from src.ticker_resolver import enrich_recommendations_with_tickers, resolve_tickers as _resolve
    stats = _resolve()
    enrich_recommendations_with_tickers()
    click.echo(f"Ticker resolution stats: {stats}")


@cli.command("refresh-prices")
@click.option("--force", is_flag=True, help="Force refresh even if cache is fresh")
def refresh_prices(force: bool) -> None:
    """Refresh stock price data from yfinance."""
    _init()
    click.echo("=== Refreshing prices ===")
    from src.price_fetcher import refresh_all_tracked_prices
    refresh_all_tracked_prices(force=force)
    click.echo("Price refresh complete")


@cli.command("build-portfolio")
def build_portfolio() -> None:
    """Build synthetic fund from recommendations."""
    _init()
    click.echo("=== Building portfolio ===")
    from src.portfolio_builder import build_performance_history, build_portfolio as _build
    holdings = _build()
    if holdings.empty:
        click.echo("No holdings built. Check that URLs are configured and pipeline has run.")
        return
    click.echo(f"Portfolio built: {len(holdings)} holdings")

    click.echo("=== Building performance history ===")
    perf = build_performance_history()
    if not perf.empty:
        click.echo(f"Performance history: {len(perf)} data points")


@cli.command("export-excel")
@click.option("--output", default=None, help="Override output file path")
def export_excel(output: str) -> None:
    """Export full dataset to Excel workbook."""
    _init()
    click.echo("=== Exporting to Excel ===")
    from src.export_excel import export_excel as _export
    path = _export(output_path=output)
    click.echo(f"Excel saved: {path}")


@cli.command("run-all")
@click.option("--force-scrape", is_flag=True)
@click.option("--force-prices", is_flag=True)
def run_all(force_scrape: bool, force_prices: bool) -> None:
    """Run the full pipeline: scrape → extract → resolve → prices → portfolio → export."""
    _init()
    steps = [
        ("Scraping", lambda: (
            __import__("src.scrape_substack", fromlist=["scrape_substack"]).scrape_substack(force_refresh=force_scrape),
            __import__("src.scrape_website", fromlist=["scrape_website"]).scrape_website(force_refresh=force_scrape),
        )),
        ("Extracting", lambda: __import__("src.extract_recommendations", fromlist=["extract_all"]).extract_all()),
        ("Resolving tickers", lambda: (
            __import__("src.ticker_resolver", fromlist=["resolve_tickers"]).resolve_tickers(),
            __import__("src.ticker_resolver", fromlist=["enrich_recommendations_with_tickers"]).enrich_recommendations_with_tickers(),
        )),
        ("Refreshing prices", lambda: __import__("src.price_fetcher", fromlist=["refresh_all_tracked_prices"]).refresh_all_tracked_prices(force=force_prices)),
        ("Building portfolio", lambda: __import__("src.portfolio_builder", fromlist=["build_portfolio"]).build_portfolio()),
        ("Building performance", lambda: __import__("src.portfolio_builder", fromlist=["build_performance_history"]).build_performance_history()),
        ("Exporting Excel", lambda: __import__("src.export_excel", fromlist=["export_excel"]).export_excel()),
    ]

    for name, fn in steps:
        click.echo(f"\n{'='*50}")
        click.echo(f"  {name}")
        click.echo(f"{'='*50}")
        t0 = time.time()
        try:
            fn()
            click.echo(f"  ✓ Done in {time.time()-t0:.1f}s")
        except Exception as exc:
            click.echo(f"  ✗ Failed: {exc}", err=True)
            logger.exception(f"Step '{name}' failed")

    click.echo("\n=== Pipeline complete ===")


if __name__ == "__main__":
    cli()
