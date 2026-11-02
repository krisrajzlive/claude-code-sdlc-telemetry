"""Load hook events and Claude Code session transcripts into DuckDB (full, idempotent reload)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb


def parse_ts(value: str) -> datetime:
    """ISO-8601 (with Z or offset) to naive UTC, matching the TIMESTAMP columns."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _jsonl(path: Path):
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def ingest_events(con: duckdb.DuckDBPyConnection, events_file: str | Path) -> int:
    path = Path(events_file)
    con.execute("DELETE FROM hook_events")
    if not path.exists():
        return 0
    rows = [
        (parse_ts(r["ts"]), r["session_id"], r["event"], r["tool"], r.get("tool_use_id", ""),
         r["name"], r["stage"], r["status"], r.get("rule", ""))
        for r in _jsonl(path)
    ]
    con.executemany("INSERT INTO hook_events VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _is_user_prompt(record: dict) -> bool:
    if record.get("type") != "user" or record.get("isSidechain") or record.get("isMeta"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(b.get("type") == "text" for b in content) and not any(
            b.get("type") == "tool_result" for b in content
        )
    return False


def ingest_transcripts(con: duckdb.DuckDBPyConnection, root: str | Path) -> dict[str, int]:
    """Parse ~/.claude/projects/**/*.jsonl. Usage is keyed by message id because Claude Code
    writes one line per content block with the same usage block."""
    usage: dict[str, tuple] = {}
    calls: dict[str, tuple] = {}
    prompts: dict[str, tuple] = {}
    for path in Path(root).expanduser().rglob("*.jsonl"):
        for rec in _jsonl(path):
            if "timestamp" not in rec or "sessionId" not in rec and "session_id" not in rec:
                continue
            session = rec.get("sessionId") or rec.get("session_id")
            ts = parse_ts(rec["timestamp"])
            message = rec.get("message") or {}
            if rec.get("type") == "assistant" and message.get("model") not in (None, "<synthetic>"):
                u = message.get("usage") or {}
                key = message.get("id") or rec.get("uuid")
                usage[key] = (
                    key, session, ts, message["model"],
                    u.get("input_tokens", 0) or 0, u.get("output_tokens", 0) or 0,
                    u.get("cache_read_input_tokens", 0) or 0,
                    u.get("cache_creation_input_tokens", 0) or 0,
                )
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_input = block.get("input") or {}
                        name = tool_input.get("skill") or tool_input.get("subagent_type") or ""
                        calls[block["id"]] = (block["id"], session, ts, block["name"], name)
            elif _is_user_prompt(rec):
                prompts[rec["uuid"]] = (rec["uuid"], session, ts)
    for table in ("api_usage", "tool_calls", "prompts"):
        con.execute(f"DELETE FROM {table}")
    con.executemany("INSERT INTO api_usage VALUES (?,?,?,?,?,?,?,?)", list(usage.values()))
    con.executemany("INSERT INTO tool_calls VALUES (?,?,?,?,?)", list(calls.values()))
    con.executemany("INSERT INTO prompts VALUES (?,?,?)", list(prompts.values()))
    return {"api_usage": len(usage), "tool_calls": len(calls), "prompts": len(prompts)}
