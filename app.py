"""Campus dashboard: reads on refresh; explicit Simulator buttons enable writes."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import streamlit as st

from monitoring.api import TandemClient
from monitoring.config import ROOT, TutorialError, load
from monitoring.dashboard import snapshot
from monitoring.execution import CONTROLLER
from monitoring.simulator_ui import render as simulator_controls
from monitoring.presentation import (DEFAULT_TIMEZONE, card_html, chart_domain, clock_label,
                                     details_rows, lab_label, noise_chart)

st.set_page_config(page_title="Computer Lab Noise Monitoring", layout="wide")
st.markdown("""<style>
.block-container {padding-top:2rem; max-width:1200px}
h1 {font-size:1.85rem !important; letter-spacing:-.03em}
.lab-card {border:1px solid var(--border-color, #8885);border-radius:12px;padding:22px;min-height:255px}
.lab-card h3 {font-size:1.12rem;margin:0 0 14px;padding:0}
.state {font-size:.95rem;font-weight:600;margin-bottom:12px}
.normal {color:light-dark(#20653e,#8bd6a8)}
.high {color:light-dark(#975400,#ffd080)}
.muted,.age,.note {color:var(--text-color);opacity:.78}
.reading {font-size:2.5rem;font-weight:600;line-height:1.25}
.reading span {font-size:1rem;font-weight:400}
.target,.age {font-size:.9rem;margin-top:6px}
.note {font-size:.82rem;min-height:24px;margin-top:12px}
</style>""", unsafe_allow_html=True)
st.title("Computer Lab Noise Monitoring")
st.caption("Simulated data")
@st.fragment(run_every=2)
def dashboard():
    controls = st.columns([2, 1, 2], vertical_alignment="bottom")
    with controls[0]:
        period = st.selectbox("Show last", ["15 minutes", "30 minutes", "1 hour", "24 hours"], index=1)
    with controls[1]:
        refresh = st.button("Refresh", type="primary", width="stretch")
    minutes = {"15 minutes": 15, "30 minutes": 30, "1 hour": 60, "24 hours": 1440}[period]
    run_state = CONTROLLER.status()
    if refresh or st.session_state.get("history_minutes") != minutes or "result" not in st.session_state or st.session_state.get("run_revision", 0) != run_state["revision"]:
        st.session_state.run_revision = run_state["revision"]
        st.session_state.history_minutes = minutes
        # Clear prior results on failure rather than imply they are current.
        st.session_state.result = None
        st.session_state.failure = None
        try:
            config = load(ROOT / "config/project.json", live=True)
            zone = config.get("display_timezone", DEFAULT_TIMEZONE)
            ZoneInfo(zone)
            with st.spinner("Updating…"):
                with TandemClient(config["region"]) as client:
                    data = snapshot(client, config, minutes)
            st.session_state.result = data
            st.session_state.zone = zone
            st.session_state.refreshed = datetime.now(timezone.utc).isoformat()
        except (TutorialError, OSError, TypeError, ValueError, KeyError):
            st.session_state.failure = "Couldn't refresh the labs. Try Refresh again. If this continues, check the app configuration and facility access."
    with controls[2]:
        if st.session_state.get("result"):
            st.caption("Last refreshed " + clock_label(st.session_state.refreshed, st.session_state.zone))
        else:
            st.caption("Last refreshed —")
    if st.session_state.get("failure"):
        st.error(st.session_state.failure)
        simulator_controls(None)
    elif st.session_state.get("result"):
        data, zone = st.session_state.result, st.session_state.zone
        now = datetime.now(timezone.utc)
        for column, card in zip(st.columns(2), data["cards"]):
            with column:
                st.markdown(card_html(card, now), unsafe_allow_html=True)
        simulator_controls({c["sensor"]: c["target"] for c in data["cards"]})
        st.subheader("Noise history")
        st.caption("Times shown in " + zone.replace("_", " "))
        for column, card in zip(st.columns(2), data["cards"]):
            with column:
                st.markdown("**" + lab_label(card["room"]) + "**")
                chart = noise_chart(data, card, zone, chart_domain(data))
                if chart is None:
                    st.info("No readings in this period. Choose a longer history range.")
                else:
                    st.altair_chart(chart, width="stretch")
        with st.expander("Reading details", expanded=False):
            st.caption("Target lines and comparisons use each room's current saved target.")
            rows = details_rows(data, zone)
            if rows:
                st.dataframe(rows, hide_index=True, column_config={
                    "Noise level (dB)": st.column_config.NumberColumn(format="%.1f"),
                    "Current target (dB)": st.column_config.NumberColumn(format="%.1f")})
            else:
                st.info("No readings in this period. Choose a longer history range.")
            issues = [lab_label(c["room"]) + ": " + {"NOT_EVALUATED": "Awaiting evaluation", "UNVERIFIED_STATUS": "Status needs checking", "STALE": "No recent reading", "NO_DATA": "No readings in this period"}.get(c["quality"], "") for c in data["cards"] if c["quality"] != "CURRENT_READBACK"]
            for issue in issues:
                st.caption(issue)
        with st.expander("Technical details", expanded=False):
            st.json({"simulator": CONTROLLER.status(), "evidence": "outputs/ui-run-*.jsonl; .state/attempts.json; .state/review.json", "source": data["source"], "refreshed_utc": st.session_state.refreshed,
                     "latest": data["cards"], "history": data["trends"]})

dashboard()
