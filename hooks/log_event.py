#!/usr/bin/env python3
"""Claude Code hook: append one normalized JSON line per hook event.

Stdlib only so it runs without installing the package. Reads the hook payload from stdin.
Command text is never stored, only a coarse stage label (test/lint/build/other).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

STAGE_PATTERNS = {
    "test": r"\b(pytest|jest|vitest|go test|node --test|cargo test|dotnet test|mvn\s+test|npm (run )?test|yarn test)\b",
    "lint": r"\b(ruff|eslint|flake8|pylint|mypy|tsc|golangci-lint|prettier --check)\b",
    "build": r"\b(npm run build|yarn build|docker build|cargo build|dotnet build|mvn\s+(package|compile)|make)\b",
}


def telemetry_dir() -> Path:
    base = os.environ.get("SDLC_TELEMETRY_DIR")
    if base:
        return Path(base)
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())) / ".sdlc-telemetry"


def classify_stage(command: str) -> str:
    for stage, pattern in STAGE_PATTERNS.items():
        if re.search(pattern, command):
            return stage
    return "other"


def build_record(payload: dict, event: str | None = None) -> dict:
    event = event or payload.get("hook_event_name", "unknown")
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    name = ""
    if tool == "Skill":
        name = tool_input.get("skill", "")
    elif tool in ("Task", "Agent"):
        name = tool_input.get("subagent_type", "")
    elif event == "SubagentStop":
        name = payload.get("agent_type") or payload.get("subagent_type") or ""
    stage = classify_stage(tool_input.get("command", "")) if tool == "Bash" else ""
    return {
        "ts": datetime.now(UTC).isoformat(),
        "session_id": payload.get("session_id", ""),
        "event": event,
        "tool": tool,
        "tool_use_id": payload.get("tool_use_id", ""),
        "name": name,
        "stage": stage,
        "status": "fail" if event == "PostToolUseFailure" else "ok",
        "rule": "",
    }


def write_event(record: dict) -> None:
    out = telemetry_dir()
    out.mkdir(parents=True, exist_ok=True)
    with (out / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        write_event(build_record(payload))
    except Exception as exc:  # noqa: BLE001  # telemetry must never break the agent
        print(f"log_event: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
