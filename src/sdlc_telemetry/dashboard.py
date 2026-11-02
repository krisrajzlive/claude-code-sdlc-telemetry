"""Streamlit dashboard over the metric views. Run via `sdlc-telemetry dashboard`."""
from __future__ import annotations

import argparse
import os
from itertools import pairwise

import numpy as np
import pandas as pd
import streamlit as st

from sdlc_telemetry import store

QUERIES = {
    "totals": "SELECT count(DISTINCT session_id) AS sessions, count(*) AS prompts FROM prompts",
    "adoption": "SELECT * FROM v_adoption_weekly ORDER BY week",
    "components": "SELECT * FROM v_component_usage ORDER BY invocations DESC",
    "gates": "SELECT * FROM v_stage_quality ORDER BY stage",
    "cycle": "SELECT * FROM v_task_cycle ORDER BY stop_ts",
    "blocks": "SELECT * FROM v_guardrail_blocks ORDER BY blocks DESC",
    "cost": "SELECT * FROM v_cost_session ORDER BY started",
    "prs": "SELECT * FROM v_pr_compare ORDER BY cohort",
    "rework": "SELECT * FROM v_rework ORDER BY cohort",
}


def load(db: str) -> dict[str, pd.DataFrame]:
    """Open, read, close: the DuckDB file lock is held only for an instant, so ingest still works."""
    con = store.connect(db)
    try:
        return {name: con.execute(sql).df() for name, sql in QUERIES.items()}
    finally:
        con.close()


def pct(value) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value * 100:.0f}%"


def empty(frame: pd.DataFrame, hint: str) -> bool:
    if frame.empty:
        st.info(hint)
    return frame.empty


def kpis(d: dict[str, pd.DataFrame]) -> None:
    totals, cost, cycle, gates = d["totals"], d["cost"], d["cycle"], d["gates"]
    test = gates[gates["stage"] == "test"]
    cols = st.columns(6)
    cols[0].metric("Sessions", int(totals["sessions"][0]))
    cols[1].metric("Prompts", int(totals["prompts"][0]))
    cols[2].metric("Cost (USD)", f"${cost['cost_usd'].sum():.2f}" if not cost.empty else "n/a")
    cache = cost["cache_read"].sum() / max(
        (cost["input_tokens"] + cost["cache_read"] + cost["cache_create"]).sum(), 1
    ) if not cost.empty else None
    cols[3].metric("Cache hit rate", pct(cache))
    cols[4].metric("Median task time", f"{cycle['seconds'].median():.0f}s" if not cycle.empty else "n/a")
    cols[5].metric("Tests first-pass", pct(test["first_pass_rate"].iloc[0]) if not test.empty else "n/a")


def tab_overview(d: dict[str, pd.DataFrame]) -> None:
    left, right = st.columns(2)
    with left:
        st.subheader("Sessions and prompts per week")
        if not empty(d["adoption"], "Ingest transcripts to see adoption."):
            st.bar_chart(d["adoption"].set_index("week")[["sessions", "prompts"]])
    with right:
        st.subheader("Cost per session (USD)")
        if not empty(d["cost"], "Ingest transcripts to see cost."):
            st.bar_chart(d["cost"].set_index("started")["cost_usd"])
    st.subheader("Task cycle time (seconds from prompt to stop)")
    if not empty(d["cycle"], "No Stop hook events yet."):
        counts, edges = np.histogram(d["cycle"]["seconds"], bins=min(10, max(len(d["cycle"]), 1)))
        labels = [f"{int(a)}-{int(b)}s" for a, b in pairwise(edges)]
        st.bar_chart(pd.DataFrame({"tasks": counts}, index=labels))


def tab_components(d: dict[str, pd.DataFrame]) -> None:
    frame = d["components"].copy()
    if empty(frame, "No Skill or Agent events yet. Run a skill or subagent with the hooks enabled."):
        return
    frame["component"] = frame["component"].replace("", "(unnamed)")
    frame["label"] = frame["kind"] + ": " + frame["component"]
    left, right = st.columns(2)
    with left:
        st.subheader("Invocations")
        st.bar_chart(frame.set_index("label")["invocations"], horizontal=True)
    with right:
        st.subheader("Failure rate")
        st.bar_chart(frame.set_index("label")["failure_rate"], horizontal=True)
    st.dataframe(frame.drop(columns="label"), width="stretch", hide_index=True)


def tab_quality(d: dict[str, pd.DataFrame]) -> None:
    st.subheader("Gate pass rate vs first-pass rate")
    if not empty(d["gates"], "No test/lint/build runs yet. Ask Claude to run your tests."):
        st.bar_chart(d["gates"].set_index("stage")[["pass_rate", "first_pass_rate"]])
        st.dataframe(d["gates"], width="stretch", hide_index=True)
    st.subheader("Guardrail blocks by rule")
    if not empty(d["blocks"], "Nothing blocked yet."):
        st.bar_chart(d["blocks"].set_index("rule")["blocks"])


def tab_delivery(d: dict[str, pd.DataFrame]) -> None:
    st.subheader("AI-assisted vs baseline PRs")
    prs = d["prs"].set_index("cohort")
    if empty(d["prs"], "Run `sdlc-telemetry ingest --repo <path>` on a repo with merged PRs."):
        pass
    elif {"ai_assisted", "baseline"} <= set(prs.index):
        cols = st.columns(3)
        for col, (label, key) in zip(
            cols, [("Median cycle (h)", "median_cycle_hours"), ("Review rounds", "avg_review_rounds"),
                   ("CI first-pass", "ci_first_pass_rate")], strict=True):
            ai, base = prs.loc["ai_assisted", key], prs.loc["baseline", key]
            delta = None if pd.isna(ai) or not base else f"{(ai - base) / base * 100:+.0f}% vs baseline"
            col.metric(label, "n/a" if pd.isna(ai) else f"{ai:g}", delta, delta_color="inverse"
                       if key != "ci_first_pass_rate" else "normal")
        st.dataframe(d["prs"], width="stretch", hide_index=True)
    else:
        st.warning("Need both ai_assisted and baseline merged PRs to compare.")
        st.dataframe(d["prs"], width="stretch", hide_index=True)
    st.subheader("Rework within 14 days (file-churn proxy)")
    if not empty(d["rework"], "Needs commits older than 14 days."):
        st.bar_chart(d["rework"].set_index("cohort")["rework_rate"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.environ.get("SDLC_DB", ".sdlc-telemetry/metrics.duckdb"))
    args, _ = parser.parse_known_args()
    st.set_page_config(page_title="Claude Code SDLC scorecard", layout="wide")
    st.title("Claude Code SDLC scorecard")
    st.caption(f"Database: {args.db}. Refresh the page after running `sdlc-telemetry ingest`.")
    data = load(args.db)
    kpis(data)
    tabs = st.tabs(["Overview", "Skills and agents", "Quality and guardrails", "Delivery"])
    for tab, render in zip(tabs, [tab_overview, tab_components, tab_quality, tab_delivery], strict=True):
        with tab:
            render(data)


main()
