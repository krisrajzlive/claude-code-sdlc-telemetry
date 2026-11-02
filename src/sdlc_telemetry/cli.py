"""sdlc-telemetry command line interface."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from sdlc_telemetry import gitci, ingest, scorecard, store

app = typer.Typer(help="Measure a Claude Code SDLC workflow.", no_args_is_help=True)

DB = typer.Option(".sdlc-telemetry/metrics.duckdb", help="DuckDB file.")


@app.command("ingest")
def ingest_cmd(
    db: str = DB,
    events: str = typer.Option(".sdlc-telemetry/events.jsonl", help="Hook event log."),
    transcripts: str | None = typer.Option(
        "~/.claude/projects", help="Claude Code transcripts root. Empty to skip."),
    repo: str | None = typer.Option(None, help="Git repo to read PRs/commits from via gh/git."),
    pricing: str | None = typer.Option(None, help="JSON file of per-model token prices."),
) -> None:
    con = store.connect(db)
    if pricing:
        store.load_pricing_file(con, pricing)
    typer.echo(f"hook events: {ingest.ingest_events(con, events)}")
    if transcripts:
        typer.echo(f"transcripts: {ingest.ingest_transcripts(con, Path(transcripts).expanduser())}")
    if repo:
        typer.echo(f"git/ci: {gitci.ingest_git(con, repo)}")


@app.command()
def report(db: str = DB, out: str | None = typer.Option(None, help="Write markdown here.")) -> None:
    text = scorecard.render(store.connect(db))
    if out:
        Path(out).write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def compare(db: str = DB) -> None:
    typer.echo(scorecard.compare(store.connect(db)))


@app.command()
def dashboard(db: str = DB) -> None:
    """Launch the Streamlit dashboard (needs the `dashboard` extra)."""
    script = Path(__file__).with_name("dashboard.py")
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(script), "--", "--db", db]))


if __name__ == "__main__":
    app()
