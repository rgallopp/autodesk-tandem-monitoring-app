# Verification and evidence

For local repository checks, run from this checkout:

```powershell
.\.venv\Scripts\python.exe -B -m monitoring preview --steps 8 --start-round 1
.\.venv\Scripts\python.exe -B -m scripts.reference_expectations
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m pip check
```

These commands are offline. The test package blocks actual HTTP; all API values/permissions/timestamps in those tests are invented. Streamlit AppTest exercises rendering using fixture-backed readers. No test reads private credentials, sends samples or changes a facility.

## Assignment evidence from Tandem and Streamlit

Use the same facility and connections throughout the run. Start with [model setup](MODEL_SETUP.md). Three [manual sends](../README.md#part-b--try-your-own-readings) are sufficient. The [guided demo](../README.md#run-the-guided-demo) is the eight-round worked example.

At each checkpoint, record the submitted dB values and collect one API readback and one refreshed app screenshot, each covering both labs:

1. **Tandem API readback.** Run the read-only command below in a second PowerShell terminal. Save its output privately for that checkpoint. Check the `connection` and `room` for both labs in `cards`, then match `measurement` and `ingested_utc` to the latest submission using `trends` and the real UTC request window in the private `outputs/ui-run-*.jsonl` audit. Verify `stored_status` on each room and compare it with the submitted value and Tandem's `target`. If a reading is still processing, repeat the read without sending another sample. If a later round has already changed the room status, its current status cannot establish what was stored at the earlier checkpoint.
2. **Streamlit screenshot.** Click **Refresh**. Capture both room cards and the noise charts after the new readings appear. Expand **Reading details** when the recorded times or exact readings need to be visible. Explain whether the returned observations warrant a visit and how the evidence changed after recovery.

```powershell
.\.venv\Scripts\python.exe -B -m monitoring read --minutes 30
```

| Checkpoint | Guided demo | What to capture at the example targets |
|---|---|---|
| Before the event | Round 1 | Lab 109 at 45.0 dB and Lab 210 at 40.0 dB, both stored as Normal |
| During the event | Rounds 2-4 | Lab 109 above 55.0 dB with stored High and Lab 210 still Normal. Round 4 offers three elevated observations for the visit decision when all readings have arrived. |
| After recovery | Rounds 5-8 | Lab 109 within target with stored Normal, plus Lab 210 still Normal. The recorded history shows the preceding event. |

Use the actual model targets if they differ from the example. Additional read-only `monitoring inspect` output can confirm the configured room properties and current stored statuses. Keep credentials, ingestion links, raw discovery data and private audit files out of shared screenshots and submissions.

Simulator previews are expected values, and the offline tests use mocked responses. The audit records request outcomes. Readback of the individual connection and the room property establishes what Tandem stored. The [historical live pilot](LIVE_HANDOFF.md#one-round-pilot-checkpoint-completed) records an earlier round 1. Collect evidence from your own run for the assignment.
