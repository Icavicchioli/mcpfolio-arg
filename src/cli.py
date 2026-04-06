# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""
Enhanced CLI with Rich formatting and Typer commands.

Provides a beautiful terminal interface with:
- Rich colors, tables, and panels
- Progress spinners
- Multiple output formats
- Interactive prompts
"""

import asyncio
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from src.config import get_settings
from src.health import HealthCheck
from src.logging_config import get_logger

app = typer.Typer(
    name="mcpfolio",
    help="🤖 MCPFolio: Local-first autonomous financial analyst",
    add_completion=True,
)

console = Console()
logger = get_logger(__name__)
settings = get_settings()


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="Stock ticker symbol (e.g., AAPL)"),
    output: str = typer.Option(None, "--output", "-o", help="Export to file (e.g., analysis.json)"),
    format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, json, markdown"
    ),
    include_news: bool = typer.Option(True, "--news/--no-news", help="Include news"),
    include_sentiment: bool = typer.Option(
        True, "--sentiment/--no-sentiment", help="Include sentiment"
    ),
):
    """Analyze a stock ticker"""
    console.print(Panel.fit(f"[bold cyan]Analyzing {ticker.upper()}[/bold cyan]"))

    with console.status("[bold yellow]Running analysis...[/bold yellow]", spinner="dots"):
        # Run analysis
        result = asyncio.run(_run_analysis(ticker, include_news, include_sentiment))

    if result:
        _display_analysis(result, format)

        if output:
            _export_analysis(result, output, format)
            console.print(f"[green]✓ Exported to {output}[/green]")
    else:
        console.print("[red]✗ Analysis failed[/red]")
        raise typer.Exit(1)


@app.command()
def web(
    port: int = typer.Option(8000, "--port", "-p", help="Port to run on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
):
    """Start web interface"""
    console.print(
        Panel.fit(
            f"[bold cyan]Starting Web UI[/bold cyan]\n\n"
            f"[green]→[/green] Open browser to: http://{host}:{port}\n"
            f"[green]→[/green] API docs: http://{host}:{port}/docs\n"
            f"[green]→[/green] Press Ctrl+C to stop",
            border_style="cyan",
        )
    )

    import uvicorn

    from src.web.main import app as web_app

    try:
        uvicorn.run(web_app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")


@app.command()
def watchlist(
    add: str = typer.Option(None, "--add", "-a", help="Add ticker to watchlist"),
    remove: str = typer.Option(None, "--remove", "-r", help="Remove ticker from watchlist"),
    show: bool = typer.Option(True, "--show/--no-show", "-s", help="Show watchlist"),
):
    """Manage watchlist"""
    # For now, just show placeholder - will integrate with session later
    if add:
        console.print(f"[green]✓ Added {add.upper()} to watchlist[/green]")

    elif remove:
        console.print(f"[yellow]Removed {remove.upper()} from watchlist[/yellow]")

    if show:
        table = Table(title="📊 Watchlist", box=box.ROUNDED)
        table.add_column("Ticker", style="cyan")
        table.add_column("Price", style="green", justify="right")
        table.add_column("Change", style="yellow", justify="right")
        table.add_column("Updated", style="dim")

        # Placeholder data
        table.add_row("AAPL", "$153.25", "+2.1%", "2 min ago")
        table.add_row("GOOGL", "$142.80", "-0.5%", "5 min ago")

        console.print(table)


@app.command()
def validate():
    """Validate system configuration and dependencies"""
    console.print("[bold cyan]Running system validation...[/bold cyan]\n")

    results = HealthCheck.run_all_checks(settings.ollama_model)

    table = Table(title="🏥 System Health Check", box=box.ROUNDED)
    table.add_column("Component", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

    for check in results["checks"]:
        status = "[green]✓[/green]" if check.passed else "[red]✗[/red]"
        table.add_row(check.name, status, check.message)

    console.print(table)

    console.print(f"\n[dim]Total duration: {results['total_duration_ms']:.0f}ms[/dim]")

    if results["all_passed"]:
        console.print("\n[bold green]✓ All checks passed![/bold green]")
    else:
        console.print("\n[bold red]✗ Some checks failed[/bold red]")
        raise typer.Exit(1)


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of entries to show"),
    ticker: str = typer.Option(None, "--ticker", "-t", help="Filter by ticker"),  # noqa: ARG001
):
    """Show analysis history"""
    console.print(f"[cyan]Recent analysis history (last {limit})...[/cyan]\n")

    table = Table(title="📜 Analysis History", box=box.ROUNDED)
    table.add_column("Ticker", style="cyan")
    table.add_column("Date", style="dim")
    table.add_column("Risk Score", justify="right")
    table.add_column("Price", style="green", justify="right")

    # Placeholder data
    table.add_row("AAPL", "2026-02-09 14:30", "45/100", "$153.25")
    table.add_row("GOOGL", "2026-02-09 13:15", "32/100", "$142.80")
    table.add_row("MSFT", "2026-02-09 11:00", "28/100", "$378.90")

    console.print(table)


@app.command()
def interactive():
    """Start interactive analysis session"""
    console.print(
        Panel.fit(
            "[bold cyan]MCPFolio Interactive Mode[/bold cyan]\n\n"
            "Type a ticker symbol to analyze (or 'quit' to exit)",
            border_style="cyan",
        )
    )

    while True:
        try:
            ticker = Prompt.ask("\n[bold cyan]mcpfolio>[/bold cyan]", default="AAPL")

            if ticker.lower() in ("quit", "exit", "q"):
                if Confirm.ask("[yellow]Exit interactive mode?[/yellow]"):
                    console.print("[cyan]👋 Goodbye![/cyan]")
                    break
                else:
                    continue

            if not ticker:
                continue

            # Run analysis
            with console.status(f"[yellow]Analyzing {ticker.upper()}...[/yellow]", spinner="dots"):
                result = asyncio.run(_run_analysis(ticker, True, True))

            if result:
                _display_analysis(result, "table")
            else:
                console.print("[red]✗ Analysis failed[/red]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Use 'quit' to exit[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


# Helper functions
async def _run_analysis(ticker: str, include_news: bool, include_sentiment: bool):
    """Run analysis via web API client"""
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/api/analyze",
                json={
                    "ticker": ticker,
                    "include_news": include_news,
                    "include_sentiment": include_sentiment,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        console.print(
            "[red]✗ Cannot connect to API server[/red]\n"
            "[yellow]Start the web server with:[/yellow] [cyan]mcpfolio web[/cyan]"
        )
        return None
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        return None


def _display_analysis(result: dict, format: str):
    """Display analysis result"""
    if format == "json":
        import json

        console.print_json(json.dumps(result, indent=2))

    elif format == "markdown":
        from rich.markdown import Markdown

        md = f"""
# Analysis: {result['ticker']}

**Risk Score:** {result['risk_score']:.0f}/100

## Market Data
- Price: ${result['market_snapshot'].get('price', 0):.2f}
- Volume: {result['market_snapshot'].get('volume', 0):,}
- Volatility: {result['market_snapshot'].get('volatility_52week', 0) * 100:.1f}%

## AI Analysis
{result['ai_analysis']}
"""
        console.print(Markdown(md))

    else:  # table format
        # Price panel
        price_panel = Panel(
            f"[bold green]${result['market_snapshot'].get('price', 0):.2f}[/bold green]\n"
            f"Volume: {result['market_snapshot'].get('volume', 0):,}\n"
            f"Volatility: {result['market_snapshot'].get('volatility_52week', 0) * 100:.1f}%",
            title=f"📈 {result['ticker']}",
            border_style="green",
        )
        console.print(price_panel)

        # Risk score
        risk_score = result["risk_score"]
        risk_color = "red" if risk_score > 70 else "yellow" if risk_score > 30 else "green"
        console.print(
            f"\n[bold]Risk Score:[/bold] [{risk_color}]{risk_score:.0f}/100[/{risk_color}]"
        )

        # Sentiment table
        if result.get("sentiment"):
            sentiment_table = Table(title="🎯 Analyst Sentiment", box=box.SIMPLE)
            sentiment_table.add_column("Firm", style="cyan")
            sentiment_table.add_column("Action", style="bold")
            sentiment_table.add_column("Grade")

            for rating in result["sentiment"][:5]:
                action = rating.get("action", "main")
                action_color = (
                    "green" if action == "up" else "red" if action == "down" else "yellow"
                )
                sentiment_table.add_row(
                    rating.get("firm", "Unknown"),
                    f"[{action_color}]{action.upper()}[/{action_color}]",
                    rating.get("grade", "N/A"),
                )

            console.print(sentiment_table)

        # AI Analysis
        console.print(
            Panel(
                result["ai_analysis"],
                title="🧠 AI Analysis",
                border_style="blue",
            )
        )


def _export_analysis(result: dict, output: str, format: str):
    """Export analysis to file"""
    import json

    output_path = Path(output)

    if format == "json":
        output_path.write_text(json.dumps(result, indent=2))
    elif format == "markdown":
        md = f"""# Analysis Report: {result['ticker']}

**Generated:** {result['timestamp']}

## Market Snapshot
- Price: ${result['market_snapshot'].get('price', 0):.2f}
- Volume: {result['market_snapshot'].get('volume', 0):,}
- Volatility: {result['market_snapshot'].get('volatility_52week', 0) * 100:.1f}%

## Risk Score
**{result['risk_score']:.0f}/100**

## AI Analysis
{result['ai_analysis']}
"""
        output_path.write_text(md)


if __name__ == "__main__":
    app()
