"""CLI: summarize all patients with bundles in SQLite."""

from pathlib import Path

from ehr_media.fhir.store import build_and_store_bundles
from ehr_media.ingestion import ingest_paths
from ehr_media.summarization.service import summarize_all

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def main() -> None:
    ingestion = ingest_paths([SAMPLE_DIR / "patients_export.json", SAMPLE_DIR / "scanned_notes.csv"])
    build_and_store_bundles(ingestion)

    summaries = summarize_all()
    for patient_id, summary in summaries.items():
        print(f"\n=== {patient_id} ({summary.confidence} confidence) ===")
        print(f"Chief concern: {summary.chief_concern}")
        print(summary.narrative)
        print(f"\n{summary.disclaimer}")


if __name__ == "__main__":
    main()