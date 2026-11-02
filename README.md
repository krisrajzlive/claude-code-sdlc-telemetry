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

1. **Wire the hooks** into the project you want to measure: copy [`hooks/`](hooks) and merge [`.claude/settings.json`](.claude/settings.json) into that project's `.claude/settings.json`.
2. Work with Claude Code as usual. Events accumulate in `.sdlc-telemetry/events.jsonl`.
3. Ingest and report:

```bash
sdlc-telemetry ingest --repo . --pricing pricing.json
sdlc-telemetry report
sdlc-telemetry compare
sdlc-telemetry dashboard
```

Transcripts already on disk are ingested retroactively, so adoption and cost history exist before the hooks do.

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
