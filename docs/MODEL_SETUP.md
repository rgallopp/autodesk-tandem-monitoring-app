# Model setup: Computer Lab Noise Monitoring

Select two **different room instances**, checking their names, numbers, owning model and Revit Comments. The reference uses Computer Lab A 109 (collaborative BIM work) and Computer Lab B 210 (quiet individual BIM work). These roles provide context; the application evaluates only readings and targets.

## Parameter and assignment table

All three custom parameters use **Element context**.

| Parameter | Purpose | Data type | Unit / storage | Template assignment |
|---|---|---|---|---|
| Noise Level | Incoming measured value on each connection | Number | Sound Pressure Level → Decibels → dB; precision 1; direct numeric dB | OmniClass 23.60.10.00 General Measuring Instruments |
| Noise Target | Per-room threshold read when evaluating | Number | Same specification/unit/precision; 55.0 for 109 and 50.0 for 210 | OmniClass 13.53 Laboratory Spaces; value saved on room |
| Noise Status | Stored rule result | Restricted Text | Exact case-sensitive values Normal and High; empty until evaluated | OmniClass 13.53 Laboratory Spaces; written on room |

Save and apply the facility template. Check the actual schema in each owning model: qualified IDs can differ between the default model and the room model. The inspected setup reports numeric type 3, restricted Text type 20 and context `e`. Confirm both numeric parameters report `soundPressureLevel / decibels / dB / precision 1`. Do not choose a generic unitless number or convert dB to another scale.

| Individual connection | Classification | Host | Rooms relationship | Pending source mapping |
|---|---|---|---|---|
| Noise_ComputerLabA_109 | 23.60.10.00 | Computer Lab A 109 | Computer Lab A 109 | noise_db → Noise Level |
| Noise_ComputerLabB_210 | 23.60.10.00 | Computer Lab B 210 | Computer Lab B 210 | noise_db → Noise Level |

For a new setup, supply the Individual Copy Links privately and follow the [mapping setup](LIVE_HANDOFF.md#mapping-setup-stage) if you need initial samples to expose `noise_db`. Use the links for the two lab noise connections. The [live handoff](LIVE_HANDOFF.md) records the supplied facility's setup and initial pilot evidence.

## Private configuration and access

| Private value | Where it belongs / how obtained |
|---|---|
| APS_CLIENT_ID and APS_CLIENT_SECRET | This repository's ignored `.env`; credentials for your authorized APS app |
| TANDEM_LAB_A_URL / TANDEM_LAB_B_URL | Same `.env`; each new noise connection's Individual ingestion Copy Link; contains a secret |
| facility_urn and region | Ignored `config/project.json`; selected facility and configured region |
| connection_key | Discovery/export, cross-checked against each new Copy Link |
| asset.model_urn and element_key | Room's actual owning model and short element key from discovery |
| parameters.noise_db | Noise Level qualified ID in the default connection model |
| asset.target_parameter / status_parameter | Noise Target / Noise Status qualified IDs in the room model |
| asset.number_parameter / comments_parameter | Source Number / Comments IDs in the room schema |
| expected_connection_name, asset.expected_name, asset.expected_number, asset.comments_contains, classifications | Match the selected connection name, room name and number, Revit Comments text, and classifications in your facility |

APS reads use `data:read`. Manual sends, the guided demo, and the command-line pilot use `data:read data:write` and require **facility Edit access** for the APS app. In Tandem, open the facility's **Users**, then **Services**, select the app identified by your local `APS_CLIENT_ID`, change **Read** to **Edit**, and save. The read-only `monitoring inspect` command reports whether status writeback is allowed. Mapping samples use read access for model checks and authenticate separately to the Individual connections.

Discovery retrieves model URNs, element/connection keys, source/custom parameter IDs, metadata, properties and saved relationships. It does not choose the intended room, create the template, assign classifications, set targets, issue ingestion secrets or save source mappings. The facility owner makes those selections in Tandem. Names are not unique identifiers; check all relationships and owning models before using discovered keys.

For inventory, save output privately:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring discover --output outputs/connections-review.json
```

Use `--model` with an owning model from that inventory for room discovery, optionally `--element` to narrow it. Files are created exclusively; use a new filename. After mapping setup, use the exact inspection command in [LIVE_HANDOFF](LIVE_HANDOFF.md).
