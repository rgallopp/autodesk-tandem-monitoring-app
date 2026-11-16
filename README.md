# Autodesk Tandem monitoring tutorial

Build a small decision-support loop: **measurements ? Tandem ? model-target rule ? verified status writeback ? Streamlit**.

The worked example is **Computer Lab Noise Monitoring**. Campus support staff use repeated elevated readings to decide whether to visit. Computer Lab A 109 supports collaborative BIM work; Computer Lab B 210 supports quiet individual BIM work. These uses are documented in the rooms' Revit Comments. A sound reading cannot identify its source, establish occupancy, or tell staff whom to approach.

This independent community tutorial is general: choose your own monitoring problem, measurement meaning, targets, rule and decision. The supplied lab example teaches separate connections, model properties, verified API data and a human decision. The illustrative targets of 55.0 and 50.0 dB are teaching settings, not prescribed limits. Synthetic readings are not calibrated sound measurements, acoustic averages or exposure estimates.

## Current reference

| Lab | Local configurable ID | Connection | Model Noise Target |
|---|---|---|---|
| Computer Lab A 109 | room-a | Noise_ComputerLabA_109 | 55.0 dB |
| Computer Lab B 210 | room-b | Noise_ComputerLabB_210 | 50.0 dB |

Three custom **Element** parameters are used: Noise Level, Noise Target and restricted Text Noise Status. Both numeric parameters use **Sound Pressure Level / Decibels / dB / one decimal**. Numbers retain that direct dB representation across payloads, model targets, API readback and display; the application performs no unit conversion.

The initial payloads are exactly `{"noise_db":45.0}` and `{"noise_db":40.0}`. The simulator uses configured numbered rounds: A is Normal in round 1, High in rounds 2?4, and Normal again in rounds 5?8. B remains Normal. No round number or timestamp is posted. Tandem supplies actual ingestion timestamps for evidence and charts.

After a measurement is retrieved from its own connection, compare it with its room's freshly read model target: **High if reading > target; otherwise Normal**. Equality is Normal. An empty status is initialized after the first verified reading. Later, mutate Noise Status only when it changes. One high reading changes status immediately; repetition supports staff judgment and does not add another rule.

## Run locally

Use Python 3.11+ and PowerShell from this repository. The setup helper creates an isolated environment and installs locked dependencies; it does not configure Tandem.

```powershell
py -3 scripts/setup_environment.py
.\.venv\Scripts\python.exe -B -m monitoring preview --steps 8 --start-round 1
.\.venv\Scripts\python.exe -B -m scripts.reference_expectations
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m pip check
```

Preview and expectations are **offline calculations**, not retained Tandem data. The suite blocks real HTTP and uses invented API fixtures, including Streamlit rendering.

Use [model setup](docs/MODEL_SETUP.md) and the [live handoff](docs/LIVE_HANDOFF.md) before any live command. Copy the public templates to ignored `.env` and `config/project.json`, then populate private values. Explicit values in this repository's `.env` take precedence over inherited process variables. No runtime dependency on a sibling checkout exists.

The mapping-setup command sends one initial sample to each validated new noise connection, accepts pending mappings, records sanitized outcomes and actual UTC send bounds, and **stops without status writeback**:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring seed --send --steps 1 --start-round 1
```

Do not repeat it merely because data is not visible. Inspect its audit first; failed or uncertain delivery is not automatically retried. Complete both mappings in Tandem before inspection or pilot. See the handoff for the staged one-round pilot and seven-round continuation, which are separate later steps.

After mappings are saved:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring inspect
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The dashboard opens at **http://localhost:8501**. It loads on opening. Click **Refresh** or choose a different **Show last** range (15 minutes, 30 minutes, 1 hour or 24 hours) to retrieve fresh data. Unrelated reruns reuse the session result; there is no automatic polling. Opening and refreshing only read Tandem. Run the simulator separately when authorized.

Each room card shows its latest retained noise reading, current model target, stored Noise Status and reading age. **High** means a verified reading exceeded its own room target; **Normal** includes equality. Empty status is **Awaiting evaluation**; a mismatch is **Status needs checking**. Readings older than five real minutes are headed **No recent reading**, with the last recorded result identified underneath. Refresh does not make an old measurement new. No readings in the selected window is different from a failed retrieval: widen the range for missing history, or retry Refresh after a retrieval failure. Failed retrievals clear the prior display rather than presenting it as current.

Separate charts show actual retained timestamps, visible points and dashed current-target lines on a common sound-level scale. Times use the configurable `display_timezone` (default **America/New_York**, including daylight saving); UTC instants are preserved in **Technical details**. Detected intervals beyond `max_history_gap_seconds` break the line; shorter missing intervals cannot be proven without a sequence identifier. Comparisons use the current saved target, not historical target versions. **Reading details** provides the human-readable observations; **Technical details** retains exact UTC values and diagnostic codes for evidence.

These are synthetic teaching readings. Room-use Comments provide background only; sound cannot establish occupancy or identify a sound source. One High reading changes the rule result immediately. Repeated elevated points support staff judgment about an in-person visit and do not automatically dispatch staff.

## Interactive Simulator

Open the app with this repository's interpreter:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Visit **http://localhost:8501** and expand **Simulator** below the room cards. Opening, Refresh, history changes, changing inputs and Preview do not send readings. **Start demo** and **Send readings** explicitly authorize writes: each uses the same CLI sequence of validated ingestion, actual retained-value readback, fresh room-target reads, rule evaluation, change-only Noise Status mutation and property verification. Inputs contain only numeric noise_db; Tandem supplies actual ingestion timestamps. No target is written by the simulator.

1. Choose **Guided demo ? Preview**. It reads current Tandem targets and displays 16 planned results for eight rounds. These are not retained measurements or verified results.
2. Click **Start demo** once. Watch round progress: at targets 55/50, A becomes High in rounds 2?4 and recovers in round 5; B remains Normal. The eight-round sequence takes at least about seven minutes, plus request/processing time. The cards and charts update from actual Tandem readback after verified rounds.
3. After completion and cooldown, select **Try your own readings**, enter **60.0** for Lab 109 and **40.0** for Lab 210, and click **Send readings** once. With targets 55/50, expected and verified statuses are High/Normal.
4. Wait for both cooldowns to expire. Enter **45.0** and **40.0** and click **Send readings** again: expected statuses are Normal/Normal. Equality is also Normal. If you changed the model targets, the rule uses those actual targets, not the teaching assumptions.
5. Compare the room cards and history with Tandem. Open **Technical details** for simulator progress and readback. Private outputs/ui-run-*.jsonl files distinguish intent, HTTP outcome, mutation acceptance and round_verified. Existing evidence is retained.

During a run, the page checks progress about every two seconds without replaying button clicks. Readback may briefly take time; pending reads are polled, while writes and failed/unknown requests are never automatically retried. Manual sends and another Start are disabled while a workflow is active. Cooldown is at least 60 seconds per connection after request completion and survives process restarts in .state/attempts.json. A cooling-down click is rejected and is never queued to send later; click again after eligibility. Guided rounds deliberately wait between their authorized sends.

**Stop** interrupts waits and checks before each subsequent API operation. The currently running operation cannot be recalled. Stop does not undo accepted measurements or property updates; a partly completed round is not counted as verified. A run may finish a round's verification if its last read was already active. The same filesystem lock excludes UI sessions and CLI writers within this checkout; other machines remain outside that safeguard.

**Closing the browser does not stop the run.** The background worker continues while the app server lives; reopen the app to see progress or press Stop before closing. A server stop/crash ends the worker without automatic restart/resume. Preserve .state/run.lock, .state/review.json and the audit. If a lock is stale, confirm the recorded process and every sender are stopped, then remove only the stale run.lock; never reset attempts.json to bypass pacing. Stop active runs before editing/restarting the server.

Verification runs automatically in the background during normal operation and after a failed or interrupted attempt. A fully resolved partial/rejected operation is recorded accurately and releases its pending marker without an acknowledgement step; it is not called a completed round. New sends still require explicit clicks and cooldown eligibility. Interrupted demos never resume their remaining rounds automatically.

**Retry verification** appears only when a recorded operation remains unresolved, with a specific explanation (for example, Lab 109's accepted reading is not returned yet, a verification request failed, or the stored status does not match the recorded expected result). The retry acquires the same local lock and checks Tandem for the original attempt. It never sends measurements. If a complete, previously sent round is now readable and no status write was attempted, it can finish the established evaluation/writeback workflow. Once a mutation intent is recorded, verification only reads its outcome and never repeats that mutation. Stop prevents new status writes; subsequent reconciliation checks the partial results only. Unknown delivery stays blocked until readback resolves it. Targets changed since a recorded evaluation require investigation rather than silently reinterpreting that write.

The persistent .state/review.json and referenced audit survive crashes. Preserve both. A stale .state/run.lock still needs the documented process check before removal; attempts.json must never be cleared to bypass pacing. Verification retry does not reset cooldown or restart a demo.

Restart the app from this repository using the command above after stopping it with Ctrl+C in its terminal. If it was launched as a hidden local helper, stop only that identified Streamlit process after stopping the run; then use the terminal command so you can manage it directly. Server restart never resumes a previous demo.

## Existing private configuration and evidence

The current configuration is schema version 2. Preserve earlier private configuration, audits and history before replacing an older template. Rebuild the private mappings from the current public template and actual discovery. Use the two new noise connections, never the previous equipment URLs. Remove obsolete result/time mappings from active private configuration; no old result property is written or deleted by this code.

Only exact Normal/High labels or IDs proven by the current restricted Text schema are accepted. Old stored labels stop execution; there is no silent relabeling. For an intentionally clean pilot, preserve prior evidence and arrange a new clearly bounded UTC evidence window, then manually clear Noise Status on the two intended rooms if needed. Keep targets and pacing state. In the supplied final setup both statuses are already empty, so no reset is needed. Mapping samples may be retained before the pilot; separate their actual UTC bounds from pilot evidence.

## Public file map

| File(s) | Purpose |
|---|---|
| `app.py` | Read-only Streamlit decision support |
| `monitoring/__init__.py`, `__main__.py` | Package and CLI preview/discover/inspect/seed/pilot/read |
| `monitoring/config.py`, `api.py` | Private configuration, credential separation, identity validation and bounded API requests |
| `monitoring/simulation.py`, `rules.py` | Deterministic numbered rounds and strict target comparison |
| `monitoring/workflow.py`, `dashboard.py`, `presentation.py`, `execution.py`, `simulator_ui.py` | Pacing, discovery checks, verified writeback and API-only presentation |
| `config/project.example.json`, `.env.example` | Public placeholders; never real secrets |
| `scripts/setup_environment.py`, `reference_expectations.py` | Environment bootstrap and generated offline reference table |
| `tests/__init__.py`, `support.py`, `test_core.py`, `test_api.py`, `test_workflow.py`, `test_app.py`, `test_execution.py`, `test_simulator_ui.py` | HTTP blocking, invented fixtures, unit/integration/UI evidence |
| `requirements.txt`, `requirements-lock.txt` | Existing dependencies and reproducible versions |
| `docs/MODEL_SETUP.md`, `LIVE_HANDOFF.md`, `REFERENCE_PILOT.md` | Setup, staged live commands and expected reference results |
| `docs/API_NOTES.md`, `SIMULATOR_COMPARISON.md` | Protocol references and pinned Autodesk source comparison |
| `docs/REVIEW.md`, `VERIFICATION.md` | Scope, limitations and evidence boundaries |
| `NOTICE.md`, `LICENSE`, `.gitignore` | Origins, retained license and private-file exclusions |

Ignored `outputs/` holds local discovery, preserved snapshots and audits; `.state/` holds the sender lock and persistent per-connection pacing. Never publish these or the private configuration. See [origins](NOTICE.md) for sibling adaptations, Autodesk references and new implementation work.
