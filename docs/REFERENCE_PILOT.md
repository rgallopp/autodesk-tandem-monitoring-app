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

Computer Lab A 109 is Normal in round 1, High in rounds 2?4 and recovers in round 5. Computer Lab B 210 stays Normal. Readings vary deterministically on the same teaching dB scale, quantized to one decimal. The configured list replaces the earlier clock-driven generator so learners can reproduce this focused sequence without posting a second field.

The reference targets are illustrative, not acoustic guidance. Revit Comments supply the collaborative/individual BIM room-use context. Elevated values are scenario inputs; neither the app nor rule infers their cause or occupancy.

The first verified reading initializes Noise Status if empty. Unchanged Normal/High values cause no mutation; repeated High readings remain in retained history. At round 4 staff can review three successive high observations. The UI's count is evidence within the returned history window, not another status rule or an automatic visit instruction.

The mapping samples are a separate preparatory stage, not the first verified pilot round. Preserve their actual UTC evidence. After saving mappings and granting Edit access, run the pilot as one round followed by a verified checkpoint and seven rounds starting at 2. See [handoff](LIVE_HANDOFF.md). Do not replay based on a status value: it cannot tell you which scenario round was last processed. There is no server run/round identifier.

Use actual Tandem ingestion timestamps for all charts and live evidence. Missing series stop the read; empty/inconsistent/stale status is explicit. Long actual-time gaps are marked for review. The application cannot prove that every scheduled request was retained from timestamps alone, and never fabricates rows for absent numbered rounds.
