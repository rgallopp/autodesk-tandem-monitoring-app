# API contracts and Autodesk references

The source comparison pins the examined Autodesk revisions in [SIMULATOR_COMPARISON](SIMULATOR_COMPARISON.md). Autodesk examples are protocol references, not bundled implementation files. Sibling MIT adaptations and new work are distinguished in [NOTICE](../NOTICE.md).

| Primary source | Use |
|---|---|
| [Python REST tutorials](https://github.com/autodesk-tandem/tutorial-rest-python/tree/aa7d0738c10407f3cc0064d07f1d2259377f6d1a) | Auth, facility/model enumeration, schema, scans, source mappings, Individual ingestion and typed property writes |
| [Read asset data](https://aps.autodesk.com/blog/how-use-tandem-data-api-retrieve-asset-data) | Per-model selected-column scan and versioned response |
| [Write asset data](https://aps.autodesk.com/blog/update-asset-data-tandem-data-api) | Repeated asset keys per mutation and real mutation timestamp |
| [Mutation reference](https://aps.autodesk.com/en/docs/tandem/v1/developers_guide/basics/mutate) | Typed custom family/column property changes |
| [Individual ingestion guidance](https://aps.autodesk.com/blog/adding-iot-sensors-tandem-api) | Numeric payload, secret link, timestamp omission and one-minute minimum |
| [Historical data guide](https://aps.autodesk.com/blog/tandem-data-api-reading-stream-data) | Numeric history keyed by actual epoch milliseconds |
| [Restricted values explanation](https://aps.autodesk.com/blog/streaming-data-unifying-multiple-iot-streams-tandem-api) | Schema allowedValues map and encoded discrete-value IDs |
| [Autodesk Text mutation clarification](https://forums.autodesk.com/t5/tandem-forum/tandem-api-call-to-mutate-elements-failed-spreadsheet-data/td-p/13625207) | Case-sensitive Text values from the allowed vocabulary |

## Request contracts

APS token: POST `https://developer.api.autodesk.com/authentication/v2/token`, Basic client ID/secret, form grant_type client_credentials. Read operations and mapping bootstrap request `data:read`; a later pilot requests `data:read data:write` and also requires facility Edit access. The facility response's `accessLevel` is checked independently of OAuth scope.

API base: `https://developer.api.autodesk.com/tandem/v1/`, with Bearer and Region headers.

| Operation | Method / path | Shape |
|---|---|---|
| Facility/models/access | GET twins/{facilityURN} | links[].modelId; accessLevel |
| Schema | GET modeldata/{modelURN}/schema | attributes[] with qualified IDs, type/context, unit/precision and allowedValues |
| Current properties | POST modeldata/{modelURN}/scan | short keys, qualifiedColumns, includeHistory:false, skipArrays:true; response starts with v1 |
| Saved mapping | GET models/{defaultModelURN}/stream-configs | elementId, streamSettings.sourceMapping; expose only safe flat source fields |
| History | GET timeseries/models/{defaultModelURN}/streams/{fullConnectionKey} | substream parameter; actual epoch-millisecond keys and numeric values |
| Status mutation | POST modeldata/{roomModelURN}/mutate | keys and muts same length, one entry per changed room status; require real response timestamp |

Individual ingestion goes separately to the validated `tandem.autodesk.com` Copy Link destination with Basic credentials passed outside the URL. No APS token is sent there. Body contains only numeric `noise_db`. No client timestamp or numbered-round field is posted; Tandem supplies actual ingestion time.

Noise Level is read in the default connection model. Noise Target and Noise Status are read/written in each room's owning model using IDs from that model's schema, which may differ from default-model IDs. Native schema dB metadata is checked; payload 45.0, target 55.0 and returned 45.0 are on the same direct numeric dB scale. Saved incoming-unit choices must also be checked in the UI; exact readback detects conversion/aggregation that changes values.

Restricted Text mutations send the exact label, for example `["i","z","STATUS_COLUMN","High"]`. Readback accepts either canonical labels or an unambiguous value ID from this property's own allowedValues map. Empty is not Normal. Arbitrary numeric/string substitutions and old labels are rejected. Actual restricted Text mutation/retention is still a later live pilot check.

## Identity, bounds and failure handling

Connections use full logical keys; scans/mutations use short element keys. Cross-model references contain model bytes plus the element key. For this lab example both `x:p` (Host) and effective `x:r` / `x:!r` (Rooms, including override) must resolve to the selected room. Empty explicit room overrides suppress the inherited room reference.

Requests disable redirects and implicit netrc/environment credentials, use connect/read timeouts, and bound response sizes. History uses strict shapes, day-aware pagination and bounded ranges/pages. Pending retention/property reads alone are polled; authentication/network failures and all writes have no automatic retry. Successful empty ingestion bodies are permitted, and actual HTTP status is recorded.

After both accepted pilot sends, read retained values within actual request UTC bounds, compare exact one-decimal values, reread model targets/state, evaluate, check for concurrent changes, mutate changed statuses and verify properties. No target/classification/relationship is modified. An unchanged status produces no mutation. Mutation response time and actual ingestion time are different API timestamps.

There is no transaction, server compare-and-swap or exactly-once guarantee. See [REVIEW](REVIEW.md) for clock, concurrency, partial-write and quality limitations. Mapping setup is intentionally separate: HTTP acceptance without saved mappings is not retained-history verification.
