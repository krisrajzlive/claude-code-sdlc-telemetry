"""Enable telemetry in another project: copy the hook scripts and merge settings idempotently."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

SKILL_AGENT = "Skill|Task|Agent"
# (event, matcher, script). Matchers cover "Task" and "Agent": the subagent tool name varies by version.
HOOK_PLAN = [
    ("UserPromptSubmit", None, "log_event.py"),
    ("PreToolUse", "Bash|Write|Edit|MultiEdit", "guard.py"),
    ("PreToolUse", SKILL_AGENT, "log_event.py"),
    ("PostToolUse", f"{SKILL_AGENT}|Bash", "log_event.py"),
    ("PostToolUseFailure", f"{SKILL_AGENT}|Bash", "log_event.py"),
    ("SubagentStop", None, "log_event.py"),
    ("Stop", None, "log_event.py"),
]
GITIGNORE_LINE = ".sdlc-telemetry/"


def hooks_source() -> Path:
    """Wheel installs ship the scripts as package data; a source checkout uses ./hooks."""
    packaged = Path(__file__).with_name("_hooks")
    return packaged if packaged.is_dir() else Path(__file__).parents[2] / "hooks"


def transcripts_dir(project: Path) -> Path:
    """Claude Code names a project's transcript folder after its path, non-alphanumerics as '-'."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))


def _command(script: str) -> str:
    return f'python "$CLAUDE_PROJECT_DIR/hooks/{script}"'


def _merge_settings(settings: dict, use_guard: bool) -> list[str]:
    actions = []
    hooks = settings.setdefault("hooks", {})
    for event, matcher, script in HOOK_PLAN:
        if script == "guard.py" and not use_guard:
            continue
        groups = hooks.setdefault(event, [])
        label = f"{event} [{matcher or '*'}] -> {script}"
        existing = next(
            (g for g in groups if any(f"hooks/{script}" in h.get("command", "") for h in g.get("hooks", []))),
            None,
        )
        if existing is None:
            group = {"hooks": [{"type": "command", "command": _command(script)}]}
            if matcher:
                group = {"matcher": matcher, **group}
            groups.append(group)
            actions.append(f"added     {label}")
        elif existing.get("matcher") != matcher:
            if matcher:
                existing["matcher"] = matcher
            else:
                existing.pop("matcher", None)
            actions.append(f"updated   {label}")
        else:
            actions.append(f"unchanged {label}")
    return actions


def install(project: str | Path, use_guard: bool = True, dry_run: bool = False) -> list[str]:
    project = Path(project).resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"project folder not found: {project}")
    actions: list[str] = []

    source = hooks_source()
    names = ["log_event.py"] + (["guard.py"] if use_guard else [])
    for name in names:
        target = project / "hooks" / name
        if target.exists() and target.read_bytes() == (source / name).read_bytes():
            actions.append(f"unchanged hooks/{name}")
            continue
        actions.append(f"{'updated  ' if target.exists() else 'copied   '} hooks/{name}")
        if not dry_run:
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source / name, target)

    settings_path = project / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    before = json.dumps(settings, sort_keys=True)
    actions += _merge_settings(settings, use_guard)
    if json.dumps(settings, sort_keys=True) != before and not dry_run:
        settings_path.parent.mkdir(exist_ok=True)
        if settings_path.exists():
            shutil.copyfile(settings_path, settings_path.with_name("settings.json.bak"))
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    gitignore = project / ".gitignore"
    current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if GITIGNORE_LINE in current.splitlines():
        actions.append("unchanged .gitignore")
    else:
        actions.append("added     .gitignore -> " + GITIGNORE_LINE)
        if not dry_run:
            gitignore.write_text(current + ("" if current.endswith("\n") or not current else "\n")
                                 + GITIGNORE_LINE + "\n", encoding="utf-8")
    return actions
