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

The first bounded live pilot established accepted ingestion, exact retained dB values, model targets and verified Normal status writes for both labs. Subsequent dashboard rendering was checked against actual API data. Interactive simulator controls and automatic reconciliation have offline fixture evidence, including delayed, failed and interrupted operations; those tests do not independently prove every tenant timing/failure behavior. Saved live evidence remains private. The example does not establish physical calibration, operating-target suitability, multi-client coordination or exactly-once delivery.


## Limits

Readback checks actual retained timestamp/value within the request window, then fresh target/state, then mutation and fresh property verification. Polls repeat only pending reads. Network/auth/malformed-response failures stop. All writes are attempted once. An uncertain write requires investigation before resending.

There is no server compare-and-swap, exactly-once guarantee or multi-model transaction. An external writer can race the final state scan; one model can succeed before another fails. Use a single sender/writer, retain audits and inspect partial state. The target is rechecked after mutation so a changed target prevents a verified claim.

The workstation clock must be synchronized. Persisted pacing protects this checkout across restarts, not other computers. The dashboard's five-real-minute freshness policy and configurable 180-second gap-review threshold suit the one-minute pilot; reconsider them for slower operational monitoring.

The app compares history with the current target, not historical target versions. Status consistency with the newest reading is not proof of a particular mutation's provenance. Counts describe returned observations; short missing intervals cannot be reliably identified without a server sequence identifier. Missing series, empty statuses, inconsistencies, long gaps and stale results stay visible.

No sound-source recognition, occupancy inference, acoustic averaging/calibration, automatic staff dispatch, deployment or long-running scheduler is included. Campus support staff decide whether to visit and what action to take.
