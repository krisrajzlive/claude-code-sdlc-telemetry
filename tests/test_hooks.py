import json

import guard
import log_event


def test_classify_stage():
    assert log_event.classify_stage("python -m pytest -q") == "test"
    assert log_event.classify_stage("ruff check .") == "lint"
    assert log_event.classify_stage("npm run build") == "build"
    assert log_event.classify_stage("ls -la") == "other"


def test_record_names_skill_and_agent_without_command_text():
    skill = log_event.build_record(
        {"hook_event_name": "PostToolUse", "tool_name": "Skill", "tool_input": {"skill": "tdd"}})
    agent = log_event.build_record(
        {"hook_event_name": "PostToolUseFailure", "tool_name": "Task",
         "tool_input": {"subagent_type": "reviewer"}})
    bash = log_event.build_record(
        {"hook_event_name": "PostToolUse", "tool_name": "Bash",
         "tool_input": {"command": "pytest --token=hunter2"}})
    assert skill["name"] == "tdd" and skill["status"] == "ok"
    assert agent["name"] == "reviewer" and agent["status"] == "fail"
    assert bash["stage"] == "test" and "hunter2" not in json.dumps(bash)


def test_write_event_appends_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_TELEMETRY_DIR", str(tmp_path))
    log_event.write_event({"a": 1})
    log_event.write_event({"a": 2})
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert [json.loads(x)["a"] for x in lines] == [1, 2]


def test_guard_rules():
    def bash(cmd):
        return guard.evaluate({"tool_name": "Bash", "tool_input": {"command": cmd}})

    assert bash("rm -rf /") == "destructive-rm"
    assert bash("git push --force origin main") == "force-push"
    assert bash("git reset --hard HEAD~3") == "hard-reset"
    assert bash("export K=ghp_" + "a" * 36) == "secret-in-command"
    assert bash("git push origin feature") is None
    write = lambda p: guard.evaluate({"tool_name": "Write", "tool_input": {"file_path": p}})
    assert write("C:\\proj\\.env") == "env-file-write"
    assert write("proj/.env.example") is None


def test_agent_tool_name_is_captured_like_task():
    rec = log_event.build_record(
        {"hook_event_name": "PreToolUse", "tool_name": "Agent",
         "tool_input": {"subagent_type": "code-reviewer"}})
    assert rec["name"] == "code-reviewer"
