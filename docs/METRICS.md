# Metric definitions

Each metric is a DuckDB view in [`views.sql`](../src/sdlc_telemetry/views.sql). Sources: **hooks** = `hooks/log_event.py` and `hooks/guard.py`, **transcript** = `~/.claude/projects/**/*.jsonl`, **git/ci** = `gh` and `git`, **otel** = Claude Code's OpenTelemetry export (Prometheus/Grafana).

| Metric | View | Formula | Source |
|---|---|---|---|
| Weekly sessions / prompts | `v_adoption_weekly` | distinct session ids and user prompts per week | transcript |
| Skill / subagent invocations | `v_component_usage` | count of `PostToolUse` + `PostToolUseFailure` for tool `Skill` / `Task`, grouped by name | hooks |
| Skill / subagent failure rate | `v_component_usage` | failures / invocations | hooks |
| Skill / subagent latency | `v_component_usage` | `PostToolUse*` ts minus `PreToolUse` ts, matched on `tool_use_id` | hooks |
| Gate pass rate | `v_stage_quality` | passing Bash runs / all runs, per stage (test, lint, build) | hooks |
| **First-pass rate** | `v_stage_quality` | share of sessions whose first run of a stage passed | hooks |
| Task cycle time | `v_task_cycle` | `Stop` ts minus the latest preceding `UserPromptSubmit` in the same session | hooks |
| Guardrail blocks | `v_guardrail_blocks` | count of `GuardrailBlock` events per rule | hooks |
| Cost per session | `v_cost_session` | tokens x per-million prices from the `pricing` table | transcript |
| Cache hit rate | `v_cost_session` | cache_read / (input + cache_read + cache_create) | transcript |
| PR cycle time | `v_pr_compare` | median(merged_at - created_at), hours | git/ci |
| Review rounds | `v_pr_compare` | reviews in state `CHANGES_REQUESTED` per PR | git/ci |
| CI first-pass rate | `v_pr_compare` | earliest `pull_request` workflow run per branch concluded `success` | git/ci |
| Rework rate (proxy) | `v_rework` | share of commits older than 14 days whose files were touched by a later commit within 14 days | git |
| Cost / tokens / accept rate (live) | Grafana | `claude_code_cost_usage`, `claude_code_token_usage`, `claude_code_code_edit_tool_decision` | otel |

## How work is tagged as AI-assisted

A merged PR is `ai_assisted` if it has the label `ai-assisted` or any of its commits carries a `Co-Authored-By: ... Claude ...` trailer. Commits are tagged by the trailer alone. Everything else is the `baseline` cohort.

## Caveats

- **Pricing** in `store.DEFAULT_PRICING` is a single editable fallback row. Pass `--pricing pricing.json` (prefix-matched per model, longest prefix wins) so cost reflects your actual rates.
- **Rework** is a file-churn proxy, not line-level blame. It overcounts files that are legitimately hot, and it applies to both cohorts equally.
- **Transcripts** carry no developer identity, so adoption is per session, not per person.
- **Hook payload fields** (`tool_use_id`, `agent_type`) depend on your Claude Code version. Missing ids leave latency empty; counts and failure rates still work.
- **OTel metric names** in the Grafana dashboard follow the Prometheus conversion of Claude Code's metric names. Check the collector's `:8889/metrics` output against your version and adjust the panel queries if they differ.
- A fair comparison needs a baseline: ingest 4 to 8 weeks of PRs from before adoption, and change one skill or agent at a time.
