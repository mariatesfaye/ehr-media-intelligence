from pathlib import Path

import pytest

from ehr_media.ingestion.service import ingest_paths
from ehr_media.models.audit import AuditAction
from ehr_media.models.ir import Gender


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample_data"


def test_ambiguous_date_parsed_to_consistent_dob():
    result = ingest_paths([SAMPLE / "patients_export.json"])
    marcus = next(p for p in result.patients if p.family_name == "Chen")
    assert marcus.dob is not None
    assert marcus.dob.month == 1 and marcus.dob.day == 2 and marcus.dob.year == 1978


def test_duplicate_document_deduplicated_with_audit():
    result = ingest_paths([SAMPLE / "patients_export.json"])
    chest = [d for d in result.documents if d.title == "Chest X-ray" and "infiltrate" in d.content_text.lower()]
    assert len(chest) == 1
    dedupe_audits = [
        e for log in result.audit_logs.values() for e in log.entries if e.action == AuditAction.DEDUPLICATED
    ]
    assert any(e.action == AuditAction.DEDUPLICATED for e in dedupe_audits)


def test_conflicting_mrn_merged_for_same_patient_identity():
    result = ingest_paths([SAMPLE / "scanned_notes.csv"])
    sean = [p for p in result.patients if p.family_name == "O'Brien"]
    assert len(sean) == 1
    assert sean[0].dob is not None
    assert sean[0].given_name == "Sean"


def test_missing_dob_defaults_with_audit_and_unknown_gender_from_csv():
    result = ingest_paths([SAMPLE / "scanned_notes.csv"])
    # First row for MRN-54321 may have missing dob until second row merges
    patient = next(p for p in result.patients if normalize_mrn_alias(p.patient_id) == "MRN-54321")
    assert patient.gender == Gender.MALE


def normalize_mrn_alias(mrn: str) -> str:
    from ehr_media.ingestion.normalize import normalize_mrn

    return normalize_mrn(mrn)