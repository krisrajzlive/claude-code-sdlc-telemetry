import json
from datetime import UTC, datetime, timedelta

import pytest

from sdlc_telemetry import gitci, ingest, scorecard, store

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def iso(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def ev(minutes, event, tool="", name="", stage="", status="ok", rule="", use_id="", session="s1"):
    return {"ts": iso(minutes), "session_id": session, "event": event, "tool": tool,
            "tool_use_id": use_id, "name": name, "stage": stage, "status": status, "rule": rule}


@pytest.fixture
def con(tmp_path):
    events = [
        ev(0, "UserPromptSubmit"),
        ev(1, "PreToolUse", "Skill", "tdd", use_id="t1"),
        ev(2, "PostToolUse", "Skill", "tdd", use_id="t1"),
        ev(3, "PreToolUse", "Task", "reviewer", use_id="t2"),
        ev(5, "PostToolUseFailure", "Task", "reviewer", status="fail", use_id="t2"),
        ev(6, "PostToolUse", "Bash", stage="test", status="fail"),
        ev(7, "PostToolUse", "Bash", stage="test"),
        ev(8, "PostToolUse", "Bash", stage="lint"),
        ev(9, "GuardrailBlock", "Bash", status="blocked", rule="force-push"),
        ev(10, "Stop"),
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    connection = store.connect(tmp_path / "m.duckdb")
    assert ingest.ingest_events(connection, path) == len(events)
    return connection


def test_component_usage_failure_rate_and_duration(con):
    rows = {r[1]: r for r in con.execute("SELECT * FROM v_component_usage").fetchall()}
    assert rows["tdd"][2:5] == (1, 0, 0.0)
    assert rows["reviewer"][2:5] == (1, 1, 1.0)
    assert rows["reviewer"][5] == 2.0 * 60


def test_stage_first_pass_vs_overall(con):
    rows = {r[0]: r for r in con.execute("SELECT * FROM v_stage_quality").fetchall()}
    assert rows["test"][1:] == (2, 0.5, 0.0)  # eventually green, but not on the first run
    assert rows["lint"][1:] == (1, 1.0, 1.0)


def test_task_cycle_and_guardrail(con):
    assert con.execute("SELECT seconds FROM v_task_cycle").fetchone()[0] == 600
    assert con.execute("SELECT * FROM v_guardrail_blocks").fetchall() == [("force-push", 1)]


def test_transcript_dedupes_usage_and_prices_cost(tmp_path, con):
    proj = tmp_path / "projects" / "p"
    proj.mkdir(parents=True)
    usage = {"input_tokens": 1000, "output_tokens": 500,
             "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 0}
    lines = [
        {"type": "user", "uuid": "u1", "sessionId": "s1", "timestamp": iso(0),
         "message": {"role": "user", "content": "fix the bug"}},
        {"type": "user", "uuid": "u2", "sessionId": "s1", "timestamp": iso(1),
         "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
        # same message id on two lines (one per content block) must count once
        {"type": "assistant", "uuid": "a1", "sessionId": "s1", "timestamp": iso(1),
         "message": {"id": "m1", "model": "claude-sonnet-5-5", "usage": usage, "content": [
             {"type": "tool_use", "id": "c1", "name": "Skill", "input": {"skill": "tdd"}}]}},
        {"type": "assistant", "uuid": "a2", "sessionId": "s1", "timestamp": iso(1),
         "message": {"id": "m1", "model": "claude-sonnet-5-5", "usage": usage, "content": [
             {"type": "tool_use", "id": "c2", "name": "Task", "input": {"subagent_type": "reviewer"}}]}},
    ]
    (proj / "s1.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    counts = ingest.ingest_transcripts(con, tmp_path / "projects")
    assert counts == {"api_usage": 1, "tool_calls": 2, "prompts": 1}
    cost, hit = con.execute("SELECT cost_usd, cache_hit_rate FROM v_cost_session").fetchone()
    assert cost == pytest.approx((1000 * 3 + 500 * 15 + 9000 * 0.30) / 1e6, abs=1e-4)
    assert hit == 0.9


def test_pr_parsing_and_compare(con):
    prs = [
        {"number": 1, "createdAt": iso(0), "mergedAt": iso(120), "headRefName": "a",
         "labels": [{"name": "ai-assisted"}], "reviews": [], "commits": [], "additions": 10, "deletions": 0},
        {"number": 2, "createdAt": iso(0), "mergedAt": iso(600), "headRefName": "b", "labels": [],
         "reviews": [{"state": "CHANGES_REQUESTED"}, {"state": "APPROVED"}],
         "commits": [{"messageBody": "x\n\nCo-Authored-By: Claude <n@a.com>", "messageHeadline": "x"}],
         "additions": 30, "deletions": 10},
        {"number": 3, "createdAt": iso(0), "mergedAt": iso(1200), "headRefName": "c", "labels": [],
         "reviews": [{"state": "CHANGES_REQUESTED"}, {"state": "CHANGES_REQUESTED"}],
         "commits": [{"messageBody": "plain", "messageHeadline": "plain"}], "additions": 20, "deletions": 0},
    ]
    runs = [{"headBranch": "a", "conclusion": "success", "createdAt": iso(1)},
            {"headBranch": "b", "conclusion": "failure", "createdAt": iso(1)},
            {"headBranch": "b", "conclusion": "success", "createdAt": iso(30)}]
    rows = gitci.parse_prs(prs, runs)
    assert [r[3] for r in rows] == [True, True, False]
    assert [r[7] for r in rows] == [True, False, None]
    con.executemany("INSERT INTO prs VALUES (?,?,?,?,?,?,?,?)", rows)
    text = scorecard.compare(con)
    assert "median_cycle_hours" in text and "-" in text  # AI PRs merge faster than the baseline PR


def test_commit_parsing_and_rework(con):
    log = (
        "\x1e" + "aaa\x1f2025-12-01T10:00:00+00:00\x1ffeat: x\n\nCo-Authored-By: Claude <n@a.com>\n\x1f\nsrc/a.py\n"
        "\x1e" + "bbb\x1f2025-12-03T10:00:00+00:00\x1ffix: a\n\x1f\nsrc/a.py\n"
        "\x1e" + "ccc\x1f2025-12-01T11:00:00+00:00\x1fdocs\n\x1f\nREADME.md\n"
    )
    rows = gitci.parse_commits(log)
    assert [r[2] for r in rows] == [True, False, False]
    assert rows[0][3] == ["src/a.py"]
    con.executemany("INSERT INTO commits VALUES (?,?,?,?)", rows)
    result = {r[0]: r[2] for r in con.execute("SELECT * FROM v_rework").fetchall()}
    assert result["ai_assisted"] == 1.0  # src/a.py touched again 2 days later
    assert result["baseline"] == 0.0  # README.md never touched again; bbb has no later commit


def test_scorecard_renders_every_section(con):
    text = scorecard.render(con)
    for title, _ in scorecard.SECTIONS:
        assert title in text
