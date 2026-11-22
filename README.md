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

## Tests

```bash
pytest -q
```