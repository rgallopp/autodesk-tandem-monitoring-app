"""Simulator controls; only explicit buttons can launch a sending workflow."""
import streamlit as st
from .config import ROOT, TutorialError, load, read_json
from .execution import CONTROLLER, availability, planned
from .rules import evaluate
from .api import TandemClient
from .workflow import preflight

def render(targets):
    try:
        config = load(ROOT / "config/project.json", live=True)
        state = CONTROLLER.status()
        ready = availability(config)
    except (TutorialError, OSError, ValueError, KeyError, TypeError):
        st.info("Simulator unavailable. Check configuration, pacing state and saved evidence.")
        return
    with st.expander("Simulator", expanded=False):
        st.caption("Sends readings and updates room statuses in Tandem.")
        disabled = bool(state["active"] or ready["busy"] or ready["review"] or any(ready["waits"].values()))
        for sensor in config["sensors"]:
            wait = ready["waits"][sensor["id"]]
            if wait:
                st.caption(f"{sensor['label']}: ready in {wait} seconds. Click again when ready; nothing is queued.")
        if ready["busy"] and not state["active"]:
            st.info("Another sender is active, or a previous server left a lock. Check Technical details.")
        if ready["review"] and not ready["busy"] and not state["active"]:
            issue = state.get("issue")
            if not issue:
                try:
                    import json
                    from pathlib import Path
                    marker = read_json(CONTROLLER.folder / "review.json")
                    records = [json.loads(line) for line in Path(marker["audit"]).read_text(encoding="utf-8").splitlines()]
                    stage = "room-status writeback" if any(r["kind"] == "mutation_intent" and r.get("round") == marker["round"] for r in records) else "stored measurement readback"
                    issue = f"Round {marker['round']}: {stage} has not been verified. Retry checks this recorded attempt without sending measurements."
                except (TutorialError, OSError, ValueError, KeyError, TypeError):
                    issue = "Recorded verification evidence could not be read. Check the saved audit."
            st.info(issue)
            if st.button("Retry verification"):
                try:
                    CONTROLLER.retry_verification(config)
                    st.rerun()
                except (TutorialError, OSError, ValueError, KeyError, TypeError):
                    st.error("Could not start verification. Check the active sender and saved evidence.")
        if targets is None:
            st.info("Refresh model data to enable new sends.")
            if state["active"]:
                st.caption(state["phase"])
                if st.button("Stop"):
                    CONTROLLER.stop()
            return
        mode = st.radio("Mode", ["Guided demo", "Try your own readings"], horizontal=True, label_visibility="collapsed")
        if mode == "Guided demo":
            st.caption("8 rounds \u00b7 at least 60 seconds between readings per lab")
            preview, start, stop = st.columns(3)
            if preview.button("Preview", disabled=state["active"]):
                try:
                    with TandemClient(config["region"]) as client:
                        _, states = preflight(client, config)
                    st.session_state.planned_rows = planned(config, {sid: v["target"] for sid, v in states.items()})
                except (TutorialError, OSError, ValueError, KeyError, TypeError):
                    st.error("Could not read model targets. Refresh and try Preview again.")
            if start.button("Start demo", disabled=disabled):
                try:
                    CONTROLLER.start(config, "guided")
                    st.rerun()
                except (TutorialError, OSError, ValueError, KeyError, TypeError):
                    st.error("Cannot start. Check cooldown, the active sender and saved evidence.")
            if stop.button("Stop", disabled=not state["active"]):
                CONTROLLER.stop()
            if st.session_state.get("planned_rows"):
                st.caption("Planned results using model targets at Preview. Actual results require verified Tandem readback.")
                st.dataframe(st.session_state.planned_rows, hide_index=True)
        else:
            values = {}
            for column, sensor, initial in zip(st.columns(2), config["sensors"], (45.0, 40.0)):
                with column:
                    sid = sensor["id"]
                    values[sid] = st.number_input(f"Lab {sensor['asset']['expected_number']} noise level (dB)", value=initial, step=0.1, format="%.1f", disabled=state["active"])
                    st.caption(f"Current Tandem target {targets[sid]:.1f} dB")
                    try:
                        st.caption("Expected status (planned): " + evaluate(values[sid], targets[sid]))
                    except (TutorialError, OSError, ValueError, KeyError, TypeError):
                        st.error("Enter a finite value with one decimal place.")
            if st.button("Send readings", disabled=disabled):
                try:
                    CONTROLLER.start(config, "custom", values)
                    st.rerun()
                except (TutorialError, OSError, ValueError, KeyError, TypeError):
                    st.error("Cannot send. Check values, cooldown, the active sender and saved evidence.")
            if st.button("Stop", disabled=not state["active"]):
                CONTROLLER.stop()
        state = CONTROLLER.status()
        if state["active"] and not state["total"]:
            st.caption(state["phase"])
        if state["total"]:
            st.write(f"Round {state['round']} of {state['total']}")
            st.progress(state["completed"] / state["total"], text=f"{state['completed']} rounds verified")
            st.caption(state["phase"])
            if state["verified"]:
                st.caption(f"Last completed round {state.get('verified_round', state['completed'])}")
            for sensor in config["sensors"]:
                status = state["verified"].get(sensor["id"])
                if status:
                    st.caption(f"Lab {sensor['asset']['expected_number']} verified \u00b7 {status}")
