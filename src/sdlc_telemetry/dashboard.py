"""Streamlit dashboard over the metric views. Run via `sdlc-telemetry dashboard`."""
from __future__ import annotations

import argparse

import streamlit as st

from sdlc_telemetry import store
from sdlc_telemetry.scorecard import SECTIONS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".sdlc-telemetry/metrics.duckdb")
    args, _ = parser.parse_known_args()
    con = store.connect(args.db)
    st.set_page_config(page_title="Claude Code SDLC scorecard", layout="wide")
    st.title("Claude Code SDLC scorecard")
    for title, sql in SECTIONS:
        st.subheader(title)
        frame = con.execute(sql).df()
        if frame.empty:
            st.caption("no data")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)


main()
