# claude-code-sdlc-telemetry

Measure a Claude Code SDLC workflow (skills, subagents, hooks) with numbers instead of anecdotes.

Three sources feed one DuckDB file, and every metric is a SQL view:

```
Claude Code hooks ──► .sdlc-telemetry/events.jsonl ─┐
~/.claude/projects transcripts ─────────────────────┼─► ingest ─► metrics.duckdb ─► scorecard / dashboard
gh + git (PRs, CI runs, commits) ───────────────────┘
Claude Code OpenTelemetry ─► collector ─► Prometheus ─► Grafana   (live cost, tokens, accept rate)
```

## What it answers

| Question | Metric |
|---|---|
| Is the workflow used? | sessions and prompts per week, skill and subagent invocation counts |
| Does each skill or agent earn its keep? | per-component failure rate and latency |
| Is the output good? | first-pass rate for test, lint and build; CI first-pass rate; review rounds; 14-day rework |
| Is it faster? | task cycle time; PR cycle time, AI-assisted vs baseline |
| Is it cheap? | cost per session, cache hit rate |
| Are guardrails working? | blocked actions per rule |

Definitions and formulas: [docs/METRICS.md](docs/METRICS.md).

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; use bin/activate on macOS/Linux
pip install -e ".[dev,dashboard]"
```

1. **Enable telemetry in the project you want to measure** (see below).
2. Restart Claude Code in that project, then work as usual. Events accumulate in that project's `.sdlc-telemetry/events.jsonl`.
3. Ingest and report (run from this repo, so the `.venv` and database are here):

```bash
sdlc-telemetry ingest --events <project>/.sdlc-telemetry/events.jsonl --transcripts ~/.claude/projects/<project-folder>
sdlc-telemetry report
sdlc-telemetry compare
sdlc-telemetry dashboard      # charts at http://localhost:8501
```

Transcripts already on disk are ingested retroactively, so adoption and cost history exist before the hooks do.

## Enable telemetry in another project

```bash
sdlc-telemetry install <path-to-project>            # add --dry-run to preview, --no-guard to skip the guardrail hook
```

This copies `hooks/log_event.py` and `hooks/guard.py` into the project, merges the hook entries into its `.claude/settings.json` **without touching existing hooks or permissions** (a `settings.json.bak` is written), and adds `.sdlc-telemetry/` to its `.gitignore`. It is safe to re-run, and re-running upgrades older hook matchers. It prints the exact `ingest` command to use, including that project's transcripts folder.

Things worth knowing:

- **Restart Claude Code** in the project after installing; settings load at session start. Hook scripts themselves are read on every call.
- **Keep `hooks/` in the project.** If a hook script is missing, Python exits with code 2, which Claude Code treats as "block this action" and your prompts will be refused. Re-run `install` to restore it.
- **Subagent tool name:** recent Claude Code versions call it `Agent`, older ones `Task`. The matchers cover both.
- **Test stage detection** recognises pytest, jest, vitest, `go test`, `node --test`, `npm test` and similar (see `STAGE_PATTERNS` in `hooks/log_event.py`). Other runners are logged as stage `other`.
- **PowerShell** drops empty-string arguments to executables, so use `ingest --no-transcripts` instead of `--transcripts ""`.
- **One events file per project.** To compare projects, ingest each into its own `--db`.
- **Manual setup**, if you prefer: copy `hooks/` and merge the `hooks` block from `.claude/settings.json`.

## Live metrics (optional)

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Claude Code exports OpenTelemetry to the collector on `:4317` (settings in `.claude/settings.json`). Prometheus is on `:9090` and Grafana on `:3000` with a provisioned "Claude Code usage" dashboard.

## Guardrails

`hooks/guard.py` blocks force-push, hard reset, `rm -rf /`, secrets in commands, and writes to `.env`. Each block is logged as a `GuardrailBlock` event, so "defects prevented" is a number. Hooks never store command text, only a stage label.

## Tagging AI-assisted work

Add the `ai-assisted` PR label or keep the `Co-Authored-By: ... Claude ...` commit trailer. Merged PRs without either form the baseline cohort for `sdlc-telemetry compare`.

## Development

```bash
pytest -q
ruff check .
```

CI runs both on Linux and Windows, plus gitleaks secret scanning.
