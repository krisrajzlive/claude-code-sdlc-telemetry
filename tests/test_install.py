import json

from sdlc_telemetry import install


def write_settings(project, data):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps(data), encoding="utf-8")


def read_settings(project):
    return json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_install_preserves_existing_hooks_and_is_idempotent(tmp_path):
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "powershell -File guard.ps1"}]}
    write_settings(tmp_path, {"permissions": {"deny": ["Bash(rm -rf /*)"]}, "hooks": {"PreToolUse": [mine]}})
    (tmp_path / ".gitignore").write_text(".DS_Store", encoding="utf-8")

    first = install.install(tmp_path)
    settings = read_settings(tmp_path)
    assert (tmp_path / "hooks" / "log_event.py").exists() and (tmp_path / "hooks" / "guard.py").exists()
    assert settings["permissions"] == {"deny": ["Bash(rm -rf /*)"]}
    assert settings["hooks"]["PreToolUse"][0] == mine  # the project's own hook is untouched
    assert {"Stop", "SubagentStop", "UserPromptSubmit", "PostToolUseFailure"} <= set(settings["hooks"])
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines() == [".DS_Store", ".sdlc-telemetry/"]
    assert (tmp_path / ".claude" / "settings.json.bak").exists()
    assert not any(a.startswith("unchanged") for a in first)

    second = install.install(tmp_path)
    assert all(a.startswith("unchanged") for a in second)
    assert read_settings(tmp_path) == settings


def test_install_upgrades_old_matcher_and_supports_dry_run_and_no_guard(tmp_path):
    cmd = {"type": "command", "command": 'python "$CLAUDE_PROJECT_DIR/hooks/log_event.py"'}
    write_settings(tmp_path, {"hooks": {"PostToolUse": [{"matcher": "Skill|Task|Bash", "hooks": [cmd]}]}})

    actions = install.install(tmp_path, dry_run=True)
    assert any(a.startswith("updated") and "PostToolUse" in a for a in actions)
    assert not (tmp_path / "hooks").exists()  # dry run writes nothing

    install.install(tmp_path, use_guard=False)
    settings = read_settings(tmp_path)
    assert settings["hooks"]["PostToolUse"][0]["matcher"] == "Skill|Task|Agent|Bash"
    assert "guard.py" not in json.dumps(settings) and not (tmp_path / "hooks" / "guard.py").exists()


def test_install_creates_settings_from_scratch_and_names_transcripts_dir(tmp_path):
    install.install(tmp_path)
    assert "Stop" in read_settings(tmp_path)["hooks"]
    folder = install.transcripts_dir(tmp_path).name
    assert "\\" not in folder and ":" not in folder and folder.endswith(tmp_path.name.replace("_", "-"))
