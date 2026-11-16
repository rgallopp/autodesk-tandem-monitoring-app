# Verification and evidence

Run from this checkout:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring preview --steps 8 --start-round 1
.\.venv\Scripts\python.exe -B -m scripts.reference_expectations
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m pip check
```

These commands are offline. The test package blocks actual HTTP; all API values/permissions/timestamps in those tests are invented. Streamlit AppTest exercises rendering using fixture-backed readers. No test reads private credentials, sends samples or changes a facility.

Checks cover direct one-decimal dB values and metadata, equality Normal, A's three High readings and recovery, B's preserved Normal status, empty-status initialization, change-only mutation, target refresh, per-connection routing, separate Host/Rooms checks, destination validation before either POST, read-only access blocking the pilot, mapping bootstrap with absent mappings, single-attempt partial/unknown outcomes, persistent pacing, read polling, genuine API-only UI data and visible quality gaps.

The generated reference table is checked against the actual public simulator/rule. Preview and expected results are not live evidence.

Live read-only discovery is separate evidence: it verified the selected room/connection identities, model/schema properties, targets, empty statuses and initial Read facility access. A later configured live preflight passed and reports Manage; the evidence files preserve both observations. Keep its raw facility identifiers private in ignored `outputs/`. Mapping request evidence must record each actual UTC start/end bound, HTTP status or unknown-delivery diagnostic, without full endpoints or secrets.

A pilot round is verified only after actual retained measurement and model property readback. Audit `ingest_intent` proves an intended request; `HTTP_ACCEPTED` proves an accepted response; neither alone proves retention. A mapping-only audit contains no `round_verified` event and makes no rule/writeback claim.

Retain earlier private evidence snapshots. Do not overwrite logs or discovery files: commands open output files exclusively. Check the handoff before any live action.
