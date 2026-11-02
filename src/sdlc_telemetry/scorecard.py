"""Render the metric views as a markdown scorecard."""
from __future__ import annotations

import duckdb

SECTIONS = [
    ("Adoption (per week)", "SELECT * FROM v_adoption_weekly ORDER BY week"),
    ("Skill and agent health", "SELECT * FROM v_component_usage ORDER BY invocations DESC"),
    ("Quality gates (test / lint / build)", "SELECT * FROM v_stage_quality ORDER BY stage"),
    ("Task cycle time (seconds, prompt to stop)",
     ("SELECT count(*) AS tasks, round(median(seconds), 1) AS median_s, "
     "round(quantile_cont(seconds, 0.9), 1) AS p90_s FROM v_task_cycle")),
    ("Guardrail blocks", "SELECT * FROM v_guardrail_blocks ORDER BY blocks DESC"),
    ("Cost and cache efficiency",
     ("SELECT count(*) AS sessions, round(sum(cost_usd), 2) AS total_usd, "
     "round(avg(cost_usd), 3) AS avg_usd_per_session, "
     "round(sum(cache_read) * 1.0 / nullif(sum(input_tokens + cache_read + cache_create), 0), 3) "
     "AS cache_hit_rate FROM v_cost_session")),
    ("PRs: AI-assisted vs baseline", "SELECT * FROM v_pr_compare ORDER BY cohort"),
    ("Rework within 14 days (file-churn proxy)", "SELECT * FROM v_rework ORDER BY cohort"),
]


def _table(columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "_no data_"
    head = "| " + " | ".join(columns) + " |\n|" + "---|" * len(columns)
    body = "\n".join("| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows)
    return f"{head}\n{body}"


def render(con: duckdb.DuckDBPyConnection, sections: list[tuple[str, str]] | None = None) -> str:
    parts = ["# Claude Code SDLC scorecard"]
    for title, sql in sections or SECTIONS:
        cursor = con.execute(sql)
        columns = [d[0] for d in cursor.description]
        parts.append(f"## {title}\n\n{_table(columns, cursor.fetchall())}")
    return "\n\n".join(parts) + "\n"


def compare(con: duckdb.DuckDBPyConnection) -> str:
    """AI-assisted vs baseline PRs with absolute and percent deltas."""
    rows = {r[0]: r for r in con.execute("SELECT * FROM v_pr_compare").fetchall()}
    if "ai_assisted" not in rows or "baseline" not in rows:
        return "Need both ai_assisted and baseline merged PRs to compare.\n"
    labels = ["prs", "median_cycle_hours", "avg_review_rounds", "ci_first_pass_rate", "avg_lines_changed"]
    out = []
    for i, label in enumerate(labels, start=1):
        base, ai = rows["baseline"][i], rows["ai_assisted"][i]
        pct = "n/a" if not base else f"{(ai - base) / base * 100:+.1f}%"
        out.append((label, base, ai, pct))
    return "# AI-assisted vs baseline\n\n" + _table(["metric", "baseline", "ai_assisted", "delta"], out) + "\n"
