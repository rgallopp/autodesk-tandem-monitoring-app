# Live handoff

The final worked example uses the [three-parameter setup table](MODEL_SETUP.md). Preserve existing evidence and use the new schema-version-2 private configuration. The two required lab selections are Computer Lab A 109 and Computer Lab B 210. Their targets are 55.0 and 50.0 dB. The two new Individual noise connections must each have its corresponding room as **both Host and Rooms relationship**.

## Current checkpoint

Read-only live discovery verified both exact room/connection matches, room numbers, Revit Comments, Laboratory Spaces / General Measuring Instruments classifications, separate connection keys, owning model identities, empty statuses, targets and matching dB schema metadata. Private identifiers are stored only in ignored files. The latest configured live preflight reports **Manage** access, sufficient for the later status-writeback stage. Earlier discovery reported Read and a users-list request returned 403; that older result is preserved separately. No permission change or status mutation was made by these scripts.

The two NEW noise Copy Links were supplied privately and passed destination checks. One mapping sample was attempted per connection on November 16, 2026; both returned HTTP 404. No retry or status mutation was attempted. Preserve the ignored mapping-sample audit and verify the current Individual ingestion links/settings in Tandem before deciding on any further send. The owner subsequently saved both mappings. A read-only `monitoring inspect` now passes both saved source mappings, room/connection checks and dB metadata, with Manage access and targets 55.0/50.0; both statuses remain empty. A read of the last 120 real minutes found no retained Noise Level for room-a and stopped before room-b history. No additional send or status mutation was attempted. The next live stage is the separate one-round pilot checkpoint, not an automatic replay of the failed mapping samples. Credentials and the facility selection were copied from authorized sibling private files; no equipment URLs were copied. Do not paste secrets into chat. File values take precedence over unrelated inherited process credentials.

## One-round pilot checkpoint completed

On November 16, 2026, the owner-authorized round 1 succeeded. Both Individual POSTs returned HTTP 200. API readback verified Lab 109 at 45.0 dB against 55.0 and Lab 210 at 40.0 against 50.0; both stored Noise Status values are now Normal. An independent read also returned CURRENT_READBACK for both labs. Actual ingestion UTC timestamps were 20:24:43.412 for 109 and 20:24:43.821 for 210. The private round_verified audit is retained; the earlier 404 evidence remains unchanged.

The seven-round continuation has not been run. The next scenario selection is start-round 2 with steps 7, preserving the existing pacing state. Do not replay round 1 based on an empty-status assumption: initialization is now complete.

## Mapping-setup stage

Validate both destination model/connection identities and current facility/room/schema relationships before either POST. The seed command deliberately bypasses the **saved mapping** requirement, not the identity/schema checks:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring seed --send --steps 1 --start-round 1
```

This command sends exactly one initial timestamp-free sample per new connection (45.0 dB for 109; 40.0 dB for 210). It uses read-only APS scope for inspection and separate Basic ingestion credentials. It records sanitized HTTP outcomes and actual UTC send start/end bounds in a new ignored audit. It does not query retained measurements, evaluate the rule or write Noise Status. If the first POST fails, it still attempts the other distinct connection once. No write is retried.

**Stop here after the samples.** In Tandem, open each new noise connection's configuration. Refresh/select its received sample, map source `noise_db` to **Noise Level**, and confirm incoming and destination units are **Decibels / dB**, with one-decimal representation. Leave timestamp mapping unset so Tandem uses actual ingestion time. Save both mappings; reopen them to verify both saved choices and the corresponding room associations. A successful HTTP response does not prove retention, and a pre-mapping sample might not be retroactively retained.

If a later inspection reports Read, restore the existing app's facility Edit access: **Users ? Services ? existing APS app (match local APS_CLIENT_ID) ? Read to Edit ? Save**. No permission or model changes are performed by these scripts.

## Inspection after mappings are saved

Run:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring inspect
```

Inspect is read-only. It checks both saved source mappings, identities, relationships and parameter metadata, and reports current targets/statuses and whether facility access permits status writeback. Empty statuses are valid before evaluation. A mapping or unit mismatch must be corrected before the pilot. The pilot separately blocks before ingestion if Edit access is still missing.

## Later pilot: one round, checkpoint, seven rounds

These are **later steps**, after mappings are saved/verified and Edit access is confirmed. They are not authorized as part of the current mapping-sample stage.

```powershell
.\.venv\Scripts\python.exe -B -m monitoring pilot --send --steps 1 --start-round 1 --interval 60
```

Verify a `round_verified` audit with each connection's actual retained dB measurement and initialized Normal status, then independently read Tandem. Check actual UTC bounds, 45.0/40.0 dB readback, 55.0/50.0 targets and both stored statuses. If a POST or mutation was uncertain, preserve evidence and investigate before any new send.

Only after the one-round checkpoint:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring pilot --send --steps 7 --start-round 2 --interval 60
.\.venv\Scripts\python.exe -B -m monitoring read --minutes 30
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Use the [generated offline expectations](REFERENCE_PILOT.md) to compare the live sequence; never label them cloud evidence. Review the dashboard after round 4 to see three retained high readings in A. Completion of the continuation shows recovery. Staff decide whether to visit.

Keep `.state/attempts.json` across commands: pacing is at least 60 real seconds per connection, measured from request completion as well as reservation. Request/processing overhead extends the run. The sender lock prevents concurrent sends from this checkout only. For a stale lock, confirm no sender is running, preserve audit/state, and remove only the stale `.state/run.lock`; do not reset pacing. A clock rollback stops execution.

Round numbers are local scenario selections recorded in audit, not server-stored sequence IDs. Readback uses actual UTC timestamps and values, with a one-second lower-bound allowance. Keep the workstation clock synchronized. Do not run another sender against these connections during the pilot.

## Streamlit opening and refresh

Run `.\.venv\Scripts\python.exe -m streamlit run app.py` in this checkout, then open http://localhost:8501. The app uses its private configuration and read-only APS scope. Opening, clicking Refresh, or changing Show last retrieves fresh data. Other reruns reuse the current session result. No simulator is launched and no status is written by the app.

Two room cards show readings, model targets, stored statuses and age; old readings are headed No recent reading. Noise history uses one chart per lab, a common dB scale, timezone-aware instants and current target lines. Reading details is collapsed; exact UTC evidence and diagnostic codes are isolated in Technical details. See the README for freshness and failure behavior. The existing first round is now old data and should not appear as a confirmed current condition. The continuation remains unstarted.

## Interactive simulator controls

The approved dashboard now includes a collapsed Simulator section. See the README Interactive Simulator walkthrough for Preview, Start demo, Stop and custom readings. Only explicit Start demo / Send readings clicks authorize sending and status updates. These UI controls call the shared CLI workflow, lock, persistent pacing and readback verification. They do not run on page opening or Refresh. This implementation was validated with offline fixtures; no new live measurements or status writes were made during integration.

Keep the server alive during a run; closing a browser leaves the worker running. Stop first when you intend to interrupt. A server restart never resumes a run; stale locks and a pending .state/review.json require evidence review as documented in the README.
