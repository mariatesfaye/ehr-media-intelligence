"""CLI entry point for Task 2: ingest sample data and persist FHIR bundles."""

from pathlib import Path

from ehr_media.fhir.store import build_and_store_bundles, print_validation_summary
from ehr_media.ingestion import ingest_paths

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def main() -> None:
    paths = [SAMPLE_DIR / "patients_export.json", SAMPLE_DIR / "scanned_notes.csv"]
    ingestion = ingest_paths(paths)
    reports = build_and_store_bundles(ingestion)
    print_validation_summary(reports)


if __name__ == "__main__":
    main()