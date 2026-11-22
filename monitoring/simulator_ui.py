"""Simulator controls; sending requires an explicit button click."""

import streamlit as st

from .config import ROOT, TutorialError, db_value, load
from .execution import CONTROLLER, availability, planned
from .rules import evaluate
from .simulation import checkpoint


def show_outcomes(config, state):
    for sensor in config["sensors"]:
        lab = state["outcomes"].get(sensor["id"], {})
        reading = lab.get("ingest_outcome")
        status = lab.get("status_outcome")
        if not reading:
            continue
        label = sensor["label"]
        if reading["outcome"] == "DELIVERY_UNKNOWN":
            st.warning(f"{label}: Reading delivery uncertain. {reading['error']}")
        elif reading["outcome"] == "HTTP_ERROR":
            st.error(f"{label}: Reading rejected. {reading['error']}")
        else:
            st.caption(f"{label}: Reading accepted (HTTP {reading['http_status']}).")
            if status and status["outcome"] == "STATUS_UPDATED":
                st.caption(f"{label}: Room status updated to {status['status']}.")
            elif status and status["outcome"] == "STATUS_UNCHANGED":
                st.caption(f"{label}: Room status already {status['status']}.")
            elif status:
                st.error(f"{label}: Status update failed. {status['error']}")
            elif not state["active"]:
                st.caption(f"{label}: Room status update did not finish.")


def render(targets):
    try:
        config = load(ROOT / "config/project.json", live=True)
        state = CONTROLLER.status()
        ready = availability(config, CONTROLLER.folder, CONTROLLER.now)
    except (TutorialError, OSError, ValueError, KeyError, TypeError):
        st.info("Simulator unavailable. Check configuration and pacing state.")
        return

    wait = max(ready["waits"].values())
    disabled = state["active"] or ready["busy"] or wait > 0
    with st.expander("Simulator", expanded=False):
        if not state["active"]:
            if ready["busy"]:
                st.info("The run lock is held by another sender or a stopped process.")
            elif wait:
                st.caption(f"Ready to send in {wait}s.")

        mode = st.radio("Mode", ["Guided demo", "Try your own readings"], horizontal=True, label_visibility="collapsed")
        values = None
        if mode == "Guided demo":
            st.caption("Before the event (round 1), during the event (2–4), after recovery (5–8).")
            preview, start = st.columns(2)
            has_targets = all(s["id"] in targets for s in config["sensors"])
            if preview.button("Preview", disabled=state["active"] or not has_targets):
                st.session_state.show_preview = True
            if has_targets and st.session_state.get("show_preview"):
                try:
                    st.dataframe(planned(config, targets), hide_index=True)
                except TutorialError as error:
                    st.error(str(error))
            clicked = start.button("Start demo", disabled=disabled)
            run_mode = "guided"
        else:
            values, valid = {}, True
            columns = st.columns(2)
            for index, sensor in enumerate(config["sensors"]):
                with columns[index % len(columns)]:
                    sid = sensor["id"]
                    target = targets.get(sid)
                    value = st.number_input(f"Lab {sensor['asset']['expected_number']} noise level (dB)",
                                            value=float(sensor["simulation"]["values"][0]), step=0.1,
                                            format="%.1f", key=f"sim_reading_{sid}", disabled=state["active"])
                    try:
                        values[sid] = db_value(value)
                        if target is not None:
                            st.caption(f"Tandem target {target:.1f} dB")
                            st.caption(f"Expected status: {evaluate(value, target)}")
                        else:
                            st.caption("Refresh to load the Tandem target.")
                    except TutorialError:
                        valid = False
                        st.error("Enter a finite value with one decimal place.")
            clicked = st.button("Send readings", disabled=disabled or not valid)
            run_mode = "custom"

        if clicked:
            try:
                CONTROLLER.start(config, run_mode, values)
                st.rerun()
            except TutorialError as error:
                st.error(str(error))
            except OSError:
                st.error("Could not start the simulator. Check local file access.")

        if state["active"] and st.button("Stop"):
            CONTROLLER.stop()
        if state["total"]:
            if state["mode"] == "guided" and state["round"]:
                st.caption(f"{checkpoint(state['round'])} · Round {state['round']} of {state['total']}")
                st.progress(state["completed"] / state["total"])
            st.caption(state["phase"])
            show_outcomes(config, state)
            if not state["active"] and any("ingest_outcome" in lab for lab in state["outcomes"].values()):
                st.caption("Use Refresh to read the stored room statuses and history from Tandem.")
