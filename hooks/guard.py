#!/usr/bin/env python3
"""Claude Code PreToolUse guardrail: block risky actions and count each block as a metric.

Exit code 2 tells Claude Code to refuse the tool call and show stderr to the model.
"""
from __future__ import annotations

import json
import re
import sys

from log_event import build_record, write_event

COMMAND_RULES = {
    "destructive-rm": r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$HOME)(\s|$)",
    "force-push": r"\bgit\s+push\b.*(--force\b|\s-f\b)",
    "hard-reset": r"\bgit\s+reset\s+--hard\b",
    "secret-in-command": r"(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,})",
}
PATH_RULES = {"env-file-write": r"(^|[\\/])\.env(\.[a-z]+)?$"}
SAFE_ENV_SUFFIXES = (".env.example", ".env.sample", ".env.template")


def evaluate(payload: dict) -> str | None:
    """Return the id of the first violated rule, or None."""
    tool_input = payload.get("tool_input") or {}
    if payload.get("tool_name") == "Bash":
        command = tool_input.get("command", "")
        for rule, pattern in COMMAND_RULES.items():
            if re.search(pattern, command):
                return rule
    if payload.get("tool_name") in ("Write", "Edit", "MultiEdit"):
        path = tool_input.get("file_path", "")
        if not path.endswith(SAFE_ENV_SUFFIXES):
            for rule, pattern in PATH_RULES.items():
                if re.search(pattern, path):
                    return rule
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    rule = evaluate(payload)
    if rule is None:
        return 0
    record = build_record(payload, event="GuardrailBlock")
    record["status"] = "blocked"
    record["rule"] = rule
    try:
        write_event(record)
    except Exception as exc:  # noqa: BLE001
        print(f"guard: {exc}", file=sys.stderr)
    print(f"Blocked by guardrail '{rule}'. Choose a safer approach.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
