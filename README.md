# EHR Media Intelligence

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Task 1 — Ingestion

```python
from pathlib import Path
from ehr_media.ingestion import ingest_paths

result = ingest_paths([
    Path("sample_data/patients_export.json"),
    Path("sample_data/scanned_notes.csv"),
])
```

## Task 2 — FHIR R4 bundles

```bash
ehr-fhir
# or
python -m ehr_media.fhir_cli
```

Bundles are stored in `data/ehr.db` (override with `DATA_DIR`). Each patient gets a `Bundle` of type `collection` with `Patient`, a synthetic `Encounter` (`enc-{patient_id}`), `DocumentReference` (linked via `context.encounter`), and `DiagnosticReport` (linked via `encounter`).

```python
from ehr_media.fhir import build_and_store_bundles, get_bundle
from ehr_media.ingestion import ingest_paths
from pathlib import Path

ingestion = ingest_paths([Path("sample_data/patients_export.json")])
reports = build_and_store_bundles(ingestion)
for r in reports:
    print(r.to_text())
```

## Task 3 — AI clinical summarization

Set `ANTHROPIC_API_KEY` in `.env`, or export `USE_MOCK_SUMMARY=1` for offline/heuristic summaries.

```bash
# assumes bundles already in data/ehr.db (run ehr-fhir first)
ehr-summarize
```

```python
from ehr_media.summarization import summarize_patient

summary = summarize_patient("MRN-67890")
print(summary.narrative)
print(summary.disclaimer)
```

Summaries are cached in SQLite (`summary_cache`) keyed by `patient_id` + FHIR `bundle_hash`.

## Tests

```bash
pytest -q
```