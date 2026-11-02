from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from sdlc_telemetry import store

APP = Path(__file__).parents[1] / "src" / "sdlc_telemetry" / "dashboard.py"


def test_dashboard_renders_on_empty_and_populated_db(tmp_path, monkeypatch):
    db = tmp_path / "m.duckdb"
    monkeypatch.setenv("SDLC_DB", str(db))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception  # empty database: every section shows an info hint

    con = store.connect(db)
    con.execute("INSERT INTO prompts VALUES ('u1', 's1', TIMESTAMP '2026-01-05 09:00:00')")
    con.execute(
        "INSERT INTO hook_events VALUES (TIMESTAMP '2026-01-05 09:01:00', 's1', 'PostToolUse', "
        "'Bash', 'x', '', 'test', 'ok', '')")
    con.close()
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert [m.label for m in app.metric][:2] == ["Sessions", "Prompts"]
