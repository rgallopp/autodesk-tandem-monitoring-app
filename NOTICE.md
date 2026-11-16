# Authorship, reuse and independent implementation

This independent community tutorial preserves the MIT attribution of
[rgallopp/autodesk-tandem-data-streaming](https://github.com/rgallopp/autodesk-tandem-data-streaming),
inspected locally at commit `815557f` (author: Ricardo Gallopp R.). The original
copyright notice and MIT permission text are retained in [LICENSE](LICENSE).

Selective adaptations:

| Source component | Adaptation in this repository |
|---|---|
| `scripts/tandem_api.py` | Literal credential loading in `monitoring/config.py`; APS token handling, safe errors, discovery and day-aware historical pagination in `monitoring/api.py` |
| `scripts/ingest-data-individual-stream-from-csv.py` | Secret URL separation, preview-first CLI, explicit sending, bounded POSTs and no write retries; now uses configured sensors, validates URL destinations against model/connection IDs, persists pacing and records write intent |
| `scripts/read_readings.py` | Qualified-ID configuration validation and API-only readback principles, adapted to single-field noise readings and typed room properties |
| `scripts/setup_environment.py` | Local environment creation/interpreter checks and dependency validation in `scripts/setup_environment.py`; unusable environments require explicit manual recovery |
| `tests/test_sender.py`, `tests/test_readback.py`, setup tests | Adapted testing scenarios for previews, credentials, redaction, paging, payloads, bounds and failures; new fixtures, assertions and rule/application integration |

New work includes the configurable simulation, numbered two-lab noise reference,
model-target rule interface, cross-model relationship validation, property mutation
and readback, restart pacing/lock, audit events, Streamlit decision support, and
this tutorial's tests and documentation.

In particular, `monitoring/simulation.py` is a new project implementation of the
configured numbered-round sequence, not a port or adaptation of Autodesk's
JavaScript simulator. The rule, restricted Text status evaluation, property
writeback orchestration/readback and Streamlit decision logic are also new project
work. The shared authentication/reader/sender foundations retain the sibling
adaptations listed above; calling the whole project an Autodesk simulator
adaptation would be inaccurate.

The desktop panel, CSV dataset, equipment lookup table, archives, generated
evidence, environment, credentials and course material were not copied. There is
no runtime import, path lookup or environment dependency on the sibling project.

Autodesk's [Python REST tutorials](https://github.com/autodesk-tandem/tutorial-rest-python)
were consulted as protocol references. No Autodesk implementation files or SDK
are copied or bundled. The sibling project recorded no upstream root license at
its inspected revision; we do not infer a license grant from public visibility.
See [API notes](docs/API_NOTES.md) for the official read/write examples inspected.

Autodesk's [stream-data-simulator](https://github.com/autodesk-tandem/stream-data-simulator)
was subsequently inspected on November 16, 2026 at revision
`dc4ac6f41a91af4968a2734ccbbe315a193fd1de` as a sending-workflow reference only.
No code from it was adapted or bundled. Its inspected tree has no LICENSE file
and its package metadata declares no license; no MIT permission is assumed.
The [source comparison](docs/SIMULATOR_COMPARISON.md) records exact revisions,
files, differences and why this project keeps its existing Python architecture.

Requests, Streamlit and their transitive dependencies are installed separately by
pip and retain their own licenses; the lock file records versions, not a license
grant for those packages. Python is distributed separately. No Autodesk or
university endorsement is claimed; no building model is supplied or licensed.
