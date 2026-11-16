# Autodesk simulator source comparison

Reviewed November 16, 2026. **Keep the current Python architecture.** The source
comparison identified useful setup clarification, not a confirmed runtime defect
requiring a rewrite. No upstream code was adapted, copied or executed for this
comparison. That comparison was read-only source inspection; later lab discovery is separately recorded in REVIEW.md.

## Revisions actually examined

Public GitHub commit metadata resolved `master`; the following source files were
then retrieved at those exact commits, rather than relying only on a README or
an unpinned browser cache:

| Repository | Examined revision | Files and purpose |
|---|---|---|
| [stream-data-simulator](https://github.com/autodesk-tandem/stream-data-simulator/tree/dc4ac6f41a91af4968a2734ccbbe315a193fd1de) | `dc4ac6f41a91af4968a2734ccbbe315a193fd1de`, committed September 10, 2024 | [src/main.js](https://github.com/autodesk-tandem/stream-data-simulator/blob/dc4ac6f41a91af4968a2734ccbbe315a193fd1de/src/main.js), [README.md](https://github.com/autodesk-tandem/stream-data-simulator/blob/dc4ac6f41a91af4968a2734ccbbe315a193fd1de/README.md), [package.json](https://github.com/autodesk-tandem/stream-data-simulator/blob/dc4ac6f41a91af4968a2734ccbbe315a193fd1de/package.json); entire source tree contains only this JavaScript implementation |
| [tutorial-rest-python](https://github.com/autodesk-tandem/tutorial-rest-python/tree/aa7d0738c10407f3cc0064d07f1d2259377f6d1a) | `aa7d0738c10407f3cc0064d07f1d2259377f6d1a`, committed July 28, 2026 | [common/auth.py](https://github.com/autodesk-tandem/tutorial-rest-python/blob/aa7d0738c10407f3cc0064d07f1d2259377f6d1a/common/auth.py), [Individual ingestion](https://github.com/autodesk-tandem/tutorial-rest-python/blob/aa7d0738c10407f3cc0064d07f1d2259377f6d1a/streams/ingest-data-individual-stream.py), [asset property writes](https://github.com/autodesk-tandem/tutorial-rest-python/blob/aa7d0738c10407f3cc0064d07f1d2259377f6d1a/assets/write-asset-properties.py); auth, separate connection endpoints, server time, schema-driven mutations |

The simulator's inspected tree has no LICENSE file, and its package metadata
declares no license. Public visibility does not grant an MIT license. These are
references; this repository does not redistribute them. Existing sibling-project
MIT adaptations remain attributed separately in [NOTICE](../NOTICE.md).

## Sending implementation comparison

| Concern | Autodesk JavaScript source at the pinned revision | Current Python lab implementation |
|---|---|---|
| Generation/configuration | Inline templates; unseeded min/max random values or array choices | Configured deterministic numbered value lists, one decimal; Normal, repeated High, recovery |
| Identification/routing | Template keys become payload id; one array POST to default-model /webhooks/generic | Explicit sensor ? Individual connection ? room; both Copy Link destinations checked before either POST |
| Authentication/requests | Caller supplies Authorization; fetch has no explicit abort deadline or overlap guard | Basic ingestion credentials separated from endpoints; APS Bearer for reads/status writes; explicit scopes, bounded timeouts, no redirects or write retries |
| Intervals | Immediate call then setInterval; TIMEOUT=5 means five minutes; nonpositive means no periodic sends | At least 60 real seconds per connection with persistent attempt/completion pacing and same-checkout lock |
| Timestamps | No reserved event timestamp | No timestamp field posted; actual Tandem ingestion timestamps used in reads, evidence and charts; scenario rounds remain local |
| Errors/evidence | Throws on 403, warns on other non-200, logs count; no retained-data readback | Sanitized HTTP/unknown outcomes and UTC send bounds; mapping setup makes no retention claim; pilot requires measurement and property readback |

Source settings are examples, not service requirements. A stream count does not prove retention. TIMEOUT denotes sending cadence, not a network deadline.

## Current requirements assessment

| Requirement | Autodesk simulator coverage | Current project |
|---|---|---|
| Two sensors / separate room connections | Multiple IDs; no association validation | Distinct Individual connections; explicit room identity, Host and Rooms checks |
| Deterministic normal / elevated / repeated / recovery | Random variation only | Configured eight-round sequence; A High 2?4, recovery 5; B always Normal |
| Model targets and dB representation | No room-target rule | Fresh Noise Target read, matching Sound Pressure Level / Decibels metadata, one-decimal direct numeric dB |
| Status writeback | Generated stream status is not a model rule result | Restricted Text Normal/High; initialize empty; mutate only changes; property readback |
| At least 60 seconds pacing | Five-minute setting exceeds minimum; no restart state | One-minute minimum enforced across restarts in this checkout |
| Read stored Tandem data for a decision | Absent | API-only Streamlit readings/targets/status/history; campus support staff decide whether to visit |

The final owner-approved simplification uses three Element parameters and numbered rounds. It no longer uses a separate synthetic clock or transition-time property. This source comparison does not add those earlier requirements back to the active workflow.

## Decisions and concrete simplifications

Keep the Python architecture and Individual ingestion. A shared webhook would add another credential/routing mode without helping the two already-created connections. The official Python Individual example confirms the separate endpoint/auth workflow.

Keep the one-minute pilot cadence. Autodesk's five-minute example is not a required setting; an eight-round sequence would then span about 35 minutes plus overhead, versus about 7 minutes at one-minute spacing. The app's five-real-minute freshness policy would need reconsideration at slower cadence.

Post only numeric noise_db. Upstream arbitrary string selections are sample data, not a substitute for this restricted Text room property. [Official ingestion guidance](https://aps.autodesk.com/blog/adding-iot-sensors-tandem-api) describes numeric ingestion and a one-minute minimum. The Python property example supports typed model mutation and skipping unchanged values.

For initial field detection, separate the mapping sample from the verified pilot. Missing saved mappings must not prevent sending a single bootstrap sample; identity, room, class, target and unit checks remain mandatory. HTTP acceptance alone is not proof of retained Noise Level.

The upstream README's Streams ? Import/Export Connections CSV fullId can assist discovery if available, but it does not select rooms, provide target/status IDs or verify associations. Keep exports private.

This project performs no dB conversion. The supplied live schema and targets establish direct numeric dB for this setup; saved incoming-unit choices and exact live readback still require verification. No Autodesk simulator code was adapted or executed. See [NOTICE](../NOTICE.md) for the actual sibling-derived foundations and new logic.

## Next live checkpoint

Use [LIVE_HANDOFF](LIVE_HANDOFF.md). After the two authorized mapping samples, save noise_db ? Noise Level on both new connections and verify units. Then run the read-only command:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring inspect
```

Status writeback and the staged one-round / seven-round pilot follow only after mappings and Edit access are verified. Offline tests establish implementation behavior, not live retention or successful mutations.
