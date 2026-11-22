# EHR Media Intelligence — Task 1: Ingestion & Cleaning

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```python
from pathlib import Path
from ehr_media.ingestion import ingest_paths

result = ingest_paths([
    Path("sample_data/patients_export.json"),
    Path("sample_data/scanned_notes.csv"),
])
```

## Tests

```bash
pytest -q
```