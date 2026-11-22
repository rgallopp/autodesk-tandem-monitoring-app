# Numbered reference pilot

**OFFLINE EXPECTATIONS ONLY.** The table is generated from the actual configured simulator and rule using assumed teaching targets 55.0 / 50.0. Live execution reads targets from Tandem; no local target fallback exists. No actual ingestion timestamp can be predicted offline.

Regenerate with:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.reference_expectations
```

| Round | Lab | Noise Level (dB) | Assumed target (dB) | Expected Noise Status | Status action |
|---|---|---|---|---|---|
| 1 | Computer Lab A 109 | 45.0 | 55.0 | Normal | initialize |
| 1 | Computer Lab B 210 | 40.0 | 50.0 | Normal | initialize |
| 2 | Computer Lab A 109 | 66.3 | 55.0 | High | change |
| 2 | Computer Lab B 210 | 45.9 | 50.0 | Normal | preserve |
| 3 | Computer Lab A 109 | 66.5 | 55.0 | High | preserve |
| 3 | Computer Lab B 210 | 45.7 | 50.0 | Normal | preserve |
| 4 | Computer Lab A 109 | 64.9 | 55.0 | High | preserve |
| 4 | Computer Lab B 210 | 46.6 | 50.0 | Normal | preserve |
| 5 | Computer Lab A 109 | 43.7 | 55.0 | Normal | change |
| 5 | Computer Lab B 210 | 45.7 | 50.0 | Normal | preserve |
| 6 | Computer Lab A 109 | 43.4 | 55.0 | Normal | preserve |
| 6 | Computer Lab B 210 | 46.2 | 50.0 | Normal | preserve |
| 7 | Computer Lab A 109 | 45.0 | 55.0 | Normal | preserve |
| 7 | Computer Lab B 210 | 46.5 | 50.0 | Normal | preserve |
| 8 | Computer Lab A 109 | 43.8 | 55.0 | Normal | preserve |
| 8 | Computer Lab B 210 | 46.6 | 50.0 | Normal | preserve |

| Checkpoint | Rounds | Lab 109 | Lab 210 |
|---|---|---|---|
| Before the event | 1 | Normal | Normal |
| During the event | 2-4 | High | Normal |
| After recovery | 5-8 | Normal | Normal |

The reference targets are teaching settings. Revit Comments give BIM room-use context. An elevated input does not identify the cause or establish occupancy.

An accepted reading is evaluated against its room's current Tandem target. The first accepted reading can initialize an empty Noise Status. Later, the app writes only when the status changes. After round 4, refresh to see whether Tandem returns three successive high readings for Lab 109. Those observations support a decision about a visit.

Use the [verification guide](VERIFICATION.md#verify-the-demo-results) to record the three checkpoints with actual Tandem timestamps and Streamlit screenshots. For the command-line version of the same scenario, see [the handoff](LIVE_HANDOFF.md).
