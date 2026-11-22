# Autodesk Tandem monitoring tutorial

Build a small decision-support loop: **measurements → Tandem → model-target rule → room status writeback → Streamlit**.

The worked example is **Computer Lab Noise Monitoring**. Campus support staff use repeated elevated readings to decide whether to visit. Computer Lab A 109 supports collaborative BIM work; Computer Lab B 210 supports quiet individual BIM work. These uses are documented in the rooms' Revit Comments. A sound reading cannot identify its source, establish occupancy, or tell staff whom to approach.

This independent community tutorial is general: choose your own monitoring problem, measurement meaning, targets, rule and decision. The supplied lab example teaches separate connections, model properties, verified API data and a human decision. The illustrative targets of 55.0 and 50.0 dB are teaching settings, not prescribed limits. Synthetic readings are not calibrated sound measurements, acoustic averages or exposure estimates.

## Choose a facility

The walkthrough uses Computer Labs 109 and 210 in the VDC Research Center. If you have access to that model, use those labs. Otherwise, follow the same noise-monitoring workflow in a Tandem facility where you can configure the rooms and connections and grant your APS app facility Edit access.

1. Choose two distinct rooms. Create a separate Individual connection for each in the facility's default model, with its room set as both **Host** and the **Rooms** relationship.
2. Follow [model setup](docs/MODEL_SETUP.md) for classifications and the three custom Element properties. Save the `noise_db` mapping to **Noise Level** on both connections. Set **Noise Target** on each room and configure **Noise Status** to allow exactly `Normal` and `High`.
3. Copy the [public template](config/project.example.json) to ignored `config/project.json`. Fill in `facility_urn`, `region`, and each sensor's `connection_key`, `expected_connection_name`, `parameters.noise_db`, and `asset` fields for the room's owning model, element, identity and property IDs. Keep the APS credentials and each connection's Copy Link in ignored `.env`, under the names used by the template and each sensor's `ingestion_env`.
4. Follow [Run locally](#run-locally), then use the [manual demo](#run-the-manual-demo) with your own readings. Start at or below both room targets, go above one target to trigger a status change, then return both readings to or below their targets.

## Current reference

| Lab | Local configurable ID | Connection | Model Noise Target |
|---|---|---|---|
| Computer Lab A 109 | room-a | Noise_ComputerLabA_109 | 55.0 dB |
| Computer Lab B 210 | room-b | Noise_ComputerLabB_210 | 50.0 dB |

Three custom **Element** parameters are used: Noise Level, Noise Target and restricted Text Noise Status. Both numeric parameters use **Sound Pressure Level / Decibels / dB / one decimal**. Numbers retain that direct dB representation across payloads, model targets, API readback and display; the application performs no unit conversion.

The first readings are `{"noise_db":45.0}` for Lab 109 and `{"noise_db":40.0}` for Lab 210. After Tandem accepts a lab's reading, the app evaluates it against that room's current Tandem target. **High** means the reading is above target. **Normal** includes equality. The app writes Noise Status if the value is empty or changes. Tandem supplies the recorded timestamps for history and evidence.

## Understand the worked example

To explore the code, you can sketch a file map or trace a Lab 109 reading from the [Simulator controls](monitoring/simulator_ui.py) through [the controller](monitoring/execution.py) and [the shared workflow](monitoring/workflow.py). An annotated UML sequence diagram can show the connection and mapping checks, the Individual request, the room target lookup, the [rule](monitoring/rules.py), the status write, and the later **Refresh** in [Streamlit](app.py) that reads [Tandem history and room properties](monitoring/dashboard.py).

An accepted POST establishes request acceptance. The history response establishes that a reading was retained, and the room property read establishes the stored status. Together, the retained readings and room status help staff decide whether to visit.

## Run locally

Use Python 3.11+ and PowerShell from this repository. Create the local environment and install the locked dependencies:

```powershell
py -3 scripts/setup_environment.py
```

If you haven't created your private files yet, copy the examples:

```powershell
Copy-Item .env.example .env
Copy-Item config/project.example.json config/project.json
```

Fill the placeholders using [model setup](docs/MODEL_SETUP.md). Explicit values in this repository's ignored `.env` take precedence over inherited process variables. For a newly created connection that needs an initial sample to expose its source field, see [first-time mapping setup](docs/LIVE_HANDOFF.md#mapping-setup-stage).

After mappings are saved:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring inspect
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The dashboard opens at **http://localhost:8501**. It reads Tandem on opening, on **Refresh**, and when you change **Show last**. The simulator's countdown and progress updates reuse the last dashboard result.

Each room card shows its latest retained noise reading, current model target, stored Noise Status and reading age. The card shows when the latest retained reading agrees with the stored status. Empty status is **Awaiting evaluation**; a mismatch is **Status needs checking**. Readings older than five real minutes are headed **No recent reading**, with the last recorded result identified underneath. Refresh does not make an old measurement new. No readings in the selected window is different from a failed retrieval: widen the range for missing history, or retry Refresh after a retrieval failure. Failed retrievals clear the prior display rather than presenting it as current.

Separate charts show actual retained timestamps, visible points and dashed current-target lines on a common sound-level scale. Times use the configurable `display_timezone` (default **America/New_York**, including daylight saving); UTC instants are preserved in **Technical details**. Detected intervals beyond `max_history_gap_seconds` break the line; shorter missing intervals cannot be proven without a sequence identifier. Comparisons use the current saved target, not historical target versions. **Reading details** provides the human-readable observations; **Technical details** retains exact UTC values and diagnostic codes for evidence.

These are synthetic teaching readings. Room-use Comments provide background only; sound cannot establish occupancy or identify a sound source. One High reading changes the rule result immediately. Repeated elevated points support staff judgment about an in-person visit and do not automatically dispatch staff.

## Interactive Simulator

Open the app at **http://localhost:8501** and expand **Simulator** below the room cards.

### Run the manual demo

Select **Try your own readings**. At each checkpoint, enter the pair below and check **Expected status** as you edit. Use the targets shown in the app if they differ from the example targets.

| Checkpoint | Lab 109 reading / expected at 55.0 dB | Lab 210 reading / expected at 50.0 dB |
|---|---|---|
| Round 1 — Normal readings | 45.0 dB / Normal | 40.0 dB / Normal |
| Round 2 — Trigger a status change | 60.0 dB / High | 50.0 dB / Normal |
| Round 3 — Return to normal | 43.7 dB / Normal | 45.7 dB / Normal |

Click **Send readings** once per row. Each lab reports acceptance or a send problem, plus the status outcome for accepted readings. When delivery is uncertain, that lab's status is left as it was. Check Tandem readback before deciding whether to send again. Capture both labs at each checkpoint with the [verification walkthrough](docs/VERIFICATION.md#verify-the-demo-results). The single cooldown countdown clears and the button re-enables automatically when ready for the next pair.

The app validates one-decimal sound pressure levels in dB and the exact status labels `Normal` and `High`. Changing the measurement type or units requires code changes to the [configuration validator](monitoring/config.py), [schema checks](monitoring/workflow.py), and display. Changing the status labels also requires updating the [rule and status validation](monitoring/rules.py) and the display. In this example, repeated above-target readings in Lab 109 give staff a reason to check that lab. Recovery means the latest reading returned within target and its room status returned to Normal.

### Run the guided demo

Select **Guided demo** and click **Preview** to see the expected results using the displayed Tandem targets. Click **Start demo** once to send the eight preset rounds. With the example targets, the scenario has three checkpoints:

| Checkpoint | Rounds | Expected Lab 109 | Expected Lab 210 |
|---|---|---|---|
| Before the event | 1 | Normal | Normal |
| During the event | 2-4 | High | Normal |
| After recovery | 5-8 | Normal | Normal |

The demo takes at least seven minutes plus request time. It uses the same per-lab send and status update as manual mode. If a request fails, the current round reports both labs and the demo stops before the next round. **Stop** ends the run after the current request. Keep the server running to finish the demo.

Both modes enforce at least 60 real seconds between sends to the same connection, using the saved state in `.state/attempts.json`. In Streamlit, writes start with **Send readings** or **Start demo**. Use [the handoff](docs/LIVE_HANDOFF.md) if a stopped server leaves a stale sender lock.

### Verify the demo results

Capture a fresh Tandem API read and a Streamlit screenshot at each checkpoint. In the guided demo, collect evidence after round 1, after one of rounds 2-4, and after a round from 5-8. Manual sends can demonstrate the same checkpoints using values at or below target, above target and back within target. Follow the [verification guide](docs/VERIFICATION.md#verify-the-demo-results) to match each reading to its connection, check the room's stored status, and decide whether a visit is warranted.

## Public file map

| File(s) | What you'll find |
|---|---|
| `scripts/setup_environment.py`, `requirements.txt`, `requirements-lock.txt` | Run the setup script to create `.venv`. The requirements files list the packages, and setup uses the locked versions. |
| `config/project.example.json`, `.env.example` | Copy these templates to `config/project.json` and `.env`. Fill in your facility, rooms, and connections in the JSON file. Keep credentials and ingestion links in `.env`. |
| [`docs/MODEL_SETUP.md`](docs/MODEL_SETUP.md) | Set up the two connections, three properties, and access in Tandem. |
| [`app.py`](app.py) | Start here to open Streamlit. The app shows Tandem readings and room statuses and includes the manual and guided simulator controls. |
| [`docs/VERIFICATION.md`](docs/VERIFICATION.md) | Check what Tandem stored with the readback command, then compare it with the refreshed Streamlit dashboard. |
| `monitoring/__init__.py`, `monitoring/__main__.py` | These files make `python -m monitoring` available. The commands include `preview` for offline sample readings, `discover` and `inspect` for setup checks, `seed` and `pilot` for sending, and `read` for stored results. |
| `monitoring/config.py`, `monitoring/api.py` | The first file loads and checks your local settings. The second sends requests to Tandem and reads its responses. |
| `monitoring/simulation.py`, `monitoring/rules.py` | The simulator prepares the preset readings. The rule compares a reading with its room's target. A reading above target is `High`, and a reading at or below target is `Normal`. |
| `monitoring/simulator_ui.py`, `monitoring/execution.py`, `monitoring/workflow.py` | Follow a click on **Send readings** from the controls to the worker that runs it. The workflow checks the connections, enforces the wait between sends, sends the readings, and updates room statuses. |
| `monitoring/dashboard.py`, `monitoring/presentation.py` | Follow **Refresh** from Tandem's stored readings and room properties to the cards and charts in Streamlit. |
| `scripts/reference_expectations.py`, [`docs/REFERENCE_PILOT.md`](docs/REFERENCE_PILOT.md), [`docs/LIVE_HANDOFF.md`](docs/LIVE_HANDOFF.md) | Generate the expected round-by-round results offline, compare them with the reference table, or find the commands for the live pilot. |
| `tests/` | Run offline checks for the rule, API client, send workflow, and Streamlit screens. The tests use sample data and block real HTTP requests. |
| [`docs/API_NOTES.md`](docs/API_NOTES.md), [`docs/SIMULATOR_COMPARISON.md`](docs/SIMULATOR_COMPARISON.md), [`docs/REVIEW.md`](docs/REVIEW.md) | Look up Tandem request details, compare this simulator with Autodesk's examples, or see the limits of what the tests and live checks establish. |
| [`NOTICE.md`](NOTICE.md), [`LICENSE`](LICENSE), `.gitignore` | Find the project credits and license, and see which local files Git ignores. |

Keep `outputs/` and `.state/` local. The first holds discovery results and run logs. The second records the last send attempt for each connection and holds the lock that prevents overlapping sends from this checkout.
