"""Collect PR, CI and commit data from `gh` and `git`, and tag AI-assisted work."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import duckdb

from sdlc_telemetry.ingest import parse_ts

AI_TRAILER = re.compile(r"co-authored-by:.*claude", re.IGNORECASE)
AI_LABEL = "ai-assisted"


def _run(args: list[str], cwd: str | Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def is_ai_pr(pr: dict) -> bool:
    if any(label.get("name") == AI_LABEL for label in pr.get("labels") or []):
        return True
    return any(
        AI_TRAILER.search((c.get("messageBody") or "") + (c.get("messageHeadline") or ""))
        for c in pr.get("commits") or []
    )


def parse_prs(prs: list[dict], runs: list[dict]) -> list[tuple]:
    """Build prs rows. CI first pass = conclusion of the earliest pull_request run per branch."""
    first_run: dict[str, dict] = {}
    for run in sorted(runs, key=lambda r: r["createdAt"]):
        first_run.setdefault(run["headBranch"], run)
    rows = []
    for pr in prs:
        run = first_run.get(pr.get("headRefName", ""))
        rows.append((
            pr["number"], parse_ts(pr["createdAt"]),
            parse_ts(pr["mergedAt"]) if pr.get("mergedAt") else None,
            is_ai_pr(pr),
            sum(1 for r in pr.get("reviews") or [] if r.get("state") == "CHANGES_REQUESTED"),
            pr.get("additions", 0), pr.get("deletions", 0),
            None if run is None else run.get("conclusion") == "success",
        ))
    return rows


def parse_commits(log_text: str) -> list[tuple]:
    """Parse output of `git log --format=%x1e%H%x1f%cI%x1f%B%x1f --name-only`."""
    rows = []
    for chunk in log_text.split("\x1e"):
        if not chunk.strip():
            continue
        sha, ts, body, files = chunk.split("\x1f", 3)
        rows.append((
            sha.strip(), parse_ts(ts.strip()), bool(AI_TRAILER.search(body)),
            [f for f in files.splitlines() if f.strip()],
        ))
    return rows


def ingest_git(con: duckdb.DuckDBPyConnection, repo: str | Path, limit: int = 500) -> dict[str, int]:
    pr_json = _run(["gh", "pr", "list", "--state", "merged", "--limit", str(limit), "--json",
                    "number,createdAt,mergedAt,labels,reviews,commits,additions,deletions,headRefName"],
                   repo)
    run_json = _run(["gh", "run", "list", "--event", "pull_request", "--limit", "300",
                     "--json", "headBranch,conclusion,createdAt"], repo)
    log = _run(["git", "log", f"-n{limit}", "--format=%x1e%H%x1f%cI%x1f%B%x1f", "--name-only"], repo)
    pr_rows = parse_prs(json.loads(pr_json), json.loads(run_json))
    commit_rows = parse_commits(log)
    con.execute("DELETE FROM prs")
    con.execute("DELETE FROM commits")
    con.executemany("INSERT INTO prs VALUES (?,?,?,?,?,?,?,?)", pr_rows)
    con.executemany("INSERT INTO commits VALUES (?,?,?,?)", commit_rows)
    return {"prs": len(pr_rows), "commits": len(commit_rows)}
