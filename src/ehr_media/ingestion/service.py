import json
from pathlib import Path

from ehr_media.ingestion.cleaning import clean_ingestion
from ehr_media.ingestion.parsers import parse_csv_notes, parse_json_export
from ehr_media.models.ir import IngestionResult


def ingest_paths(paths: list[Path]) -> IngestionResult:
    raw_patients: list[dict] = []
    raw_documents: list[dict] = []
    raw_findings: list[dict] = []

    for path in paths:
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            p, d, f = parse_json_export(path)
        elif suffix == ".csv":
            p, d, f = parse_csv_notes(path)
        else:
            continue
        raw_patients.extend(p)
        raw_documents.extend(d)
        raw_findings.extend(f)

    return clean_ingestion(raw_patients, raw_documents, raw_findings)


def save_ingestion_snapshot(result: IngestionResult, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.model_dump(mode="json")
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")