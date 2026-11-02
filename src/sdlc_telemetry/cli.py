"""sdlc-telemetry command line interface."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from sdlc_telemetry import gitci, ingest, scorecard, store
from sdlc_telemetry import install as installer

app = typer.Typer(help="Measure a Claude Code SDLC workflow.", no_args_is_help=True)

DB = typer.Option(".sdlc-telemetry/metrics.duckdb", help="DuckDB file.")
PROJECT = typer.Argument(..., help="Project folder to enable telemetry in.")


@app.command("ingest")
def ingest_cmd(
    db: str = DB,
    events: str = typer.Option(".sdlc-telemetry/events.jsonl", help="Hook event log."),
    transcripts: str | None = typer.Option(
        "~/.claude/projects", help="Claude Code transcripts root. Empty to skip."),
    no_transcripts: bool = typer.Option(False, "--no-transcripts", help="Skip transcript ingest."),
    repo: str | None = typer.Option(None, help="Git repo to read PRs/commits from via gh/git."),
    pricing: str | None = typer.Option(None, help="JSON file of per-model token prices."),
) -> None:
    con = store.connect(db)
    if pricing:
        store.load_pricing_file(con, pricing)
    typer.echo(f"hook events: {ingest.ingest_events(con, events)}")
    if transcripts and not no_transcripts:
        typer.echo(f"transcripts: {ingest.ingest_transcripts(con, Path(transcripts).expanduser())}")
    if repo:
        typer.echo(f"git/ci: {gitci.ingest_git(con, repo)}")


@app.command("install")
def install_cmd(
    project: Path = PROJECT,
    no_guard: bool = typer.Option(False, "--no-guard", help="Skip the guardrail hook."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change; write nothing."),
) -> None:
    """Copy the hook scripts into PROJECT and merge .claude/settings.json (safe to re-run)."""
    for line in installer.install(project, use_guard=not no_guard, dry_run=dry_run):
        typer.echo(line)
    if dry_run:
        typer.echo("\ndry run: nothing written.")
        return
    typer.echo(
        "\nNext:\n  1. Restart Claude Code in the project (settings load at session start).\n"
        "  2. Work normally, then from the telemetry repo run:\n"
        f"     sdlc-telemetry ingest --events \"{project.resolve() / '.sdlc-telemetry' / 'events.jsonl'}\" "
        f"--transcripts \"{installer.transcripts_dir(project)}\"\n"
        "     sdlc-telemetry report"
    )


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
