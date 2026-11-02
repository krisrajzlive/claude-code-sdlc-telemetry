"""DuckDB schema, pricing table and view loading."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS hook_events (
    ts TIMESTAMP, session_id VARCHAR, event VARCHAR, tool VARCHAR, tool_use_id VARCHAR,
    name VARCHAR, stage VARCHAR, status VARCHAR, rule VARCHAR);
CREATE TABLE IF NOT EXISTS api_usage (
    msg_id VARCHAR, session_id VARCHAR, ts TIMESTAMP, model VARCHAR,
    input_tokens BIGINT, output_tokens BIGINT, cache_read BIGINT, cache_create BIGINT);
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id VARCHAR, session_id VARCHAR, ts TIMESTAMP, tool VARCHAR, name VARCHAR);
CREATE TABLE IF NOT EXISTS prompts (uuid VARCHAR, session_id VARCHAR, ts TIMESTAMP);
CREATE TABLE IF NOT EXISTS prs (
    number INTEGER, created_at TIMESTAMP, merged_at TIMESTAMP, ai_assisted BOOLEAN,
    review_rounds INTEGER, additions INTEGER, deletions INTEGER, ci_first_pass BOOLEAN);
CREATE TABLE IF NOT EXISTS commits (
    sha VARCHAR, ts TIMESTAMP, ai_assisted BOOLEAN, files VARCHAR[]);
CREATE TABLE IF NOT EXISTS pricing (
    prefix VARCHAR, input_per_m DOUBLE, output_per_m DOUBLE,
    cache_read_per_m DOUBLE, cache_write_per_m DOUBLE);
"""

# Editable defaults (USD per million tokens). Replace with your contract rates via
# `sdlc-telemetry ingest --pricing pricing.json`.
DEFAULT_PRICING = [
    {"prefix": "", "input_per_m": 3.0, "output_per_m": 15.0,
     "cache_read_per_m": 0.30, "cache_write_per_m": 3.75},
]


def connect(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    if con.execute("SELECT count(*) FROM pricing").fetchone()[0] == 0:
        load_pricing(con, DEFAULT_PRICING)
    con.execute(resources.files("sdlc_telemetry").joinpath("views.sql").read_text("utf-8"))
    return con


def load_pricing(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    con.execute("DELETE FROM pricing")
    con.executemany(
        "INSERT INTO pricing VALUES (?, ?, ?, ?, ?)",
        [(r["prefix"], r["input_per_m"], r["output_per_m"],
          r["cache_read_per_m"], r["cache_write_per_m"]) for r in rows],
    )


def load_pricing_file(con: duckdb.DuckDBPyConnection, path: str | Path) -> None:
    load_pricing(con, json.loads(Path(path).read_text("utf-8")))
