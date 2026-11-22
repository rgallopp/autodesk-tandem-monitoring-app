# Implementation review and remaining live checks

The current architecture remains Python: isolated credential loading, bounded APS/Individual requests, discovery, persisted pacing, API readback, pure rule, owning-model writeback and a dashboard with explicit simulator write controls. The final lab revision narrows the model contract to three Element parameters and one numeric payload field. No dependencies changed.

## Confirmed corrections

- The final facility has dB metadata, so the public/private configuration and preflight now require that metadata consistently for both target and measurement. One decimal is retained across generation, payload, readback and display.
- Noise Status is restricted Text: exact Normal and High. Empty values mean uninitialized. Known schema IDs may be decoded, but unknown/old labels stop without automatic conversion.
- Explicit project `.env` values take precedence for API/sender calls. This avoids unrelated inherited APS credentials or destination URLs overriding this checkout's intended values.
- Mapping setup permits unsaved source mappings while retaining both destination/room/schema checks. It does not mutate statuses or claim retained-history verification.
- Both Host and effective Rooms relationship must match the selected lab. Each connection's own measurement is evaluated against that room's model target.

## Evidence boundaries

Offline tests use an in-memory client, controlled clock, mocked HTTP and Streamlit AppTest. They establish implemented behavior, not cloud retention, live permission to mutate, physical calibration or actual elapsed request pacing.

Read-only live discovery on November 16, 2026 separately established the two lab identities, saved target values, empty statuses, schema vocabulary/dB metadata, host/room relationships and initially facility access **Read**. A subsequent preflight using the new implementation passed and reports **Manage**, sufficient for later writeback. Complete credentials/URLs/identifiers remain private. No status mutation was used to test access.

The first bounded live pilot established accepted ingestion, exact retained dB values, model targets and verified Normal status writes for both labs. Subsequent dashboard rendering was checked against actual API data. The current simulator uses offline fixtures to cover delayed visibility, failed updates, uncertain ingestion and interruption. Saved live evidence remains private. The example does not establish physical calibration, operating-target suitability, multi-client coordination or exactly-once delivery.


## Limits

Each accepted reading is evaluated against the room's current target and can update that room's status. Refresh or use the read command to compare the retained reading and stored status. An uncertain send or status write receives one attempt. Inspect an uncertain outcome with read-only tools before deciding whether to send again.

Concurrent external writers can change a room target or status between the model read and write. The labs' requests are independent, so one may succeed while the other fails. The per-lab audit preserves the outcomes.

The workstation clock must be synchronized. Persisted pacing protects this checkout across restarts, not other computers. The dashboard's five-real-minute freshness policy and configurable 180-second gap-review threshold suit the one-minute pilot; reconsider them for slower operational monitoring.

The app compares history with the current target, not historical target versions. Status consistency with the newest reading is not proof of a particular mutation's provenance. Counts describe returned observations; short missing intervals cannot be reliably identified without a server sequence identifier. Missing series, empty statuses, inconsistencies, long gaps and stale results stay visible.

No sound-source recognition, occupancy inference, acoustic averaging/calibration, automatic staff dispatch, deployment or long-running scheduler is included. Campus support staff decide whether to visit and what action to take.
