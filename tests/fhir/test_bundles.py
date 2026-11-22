from pathlib import Path

from ehr_media.fhir.mappers import build_patient_bundle, encounter_id_for
from ehr_media.fhir.store import build_and_store_bundles, get_bundle, get_latest_validation_report
from ehr_media.fhir.validation import validate_bundle
from ehr_media.ingestion.service import ingest_paths

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [
    ROOT / "sample_data" / "patients_export.json",
    ROOT / "sample_data" / "scanned_notes.csv",
]


def test_bundle_contains_required_resource_types():
    ingestion = ingest_paths(SAMPLES)
    marcus = next(p for p in ingestion.patients if p.family_name == "Chen")
    bundle = build_patient_bundle(marcus.patient_id, ingestion)
    bundle_dict = bundle.model_dump(mode="json")

    resource_types = {e["resource"]["resourceType"] for e in bundle_dict["entry"]}
    assert resource_types >= {"Patient", "Encounter", "DocumentReference", "DiagnosticReport"}


def test_encounter_links_on_clinical_resources():
    ingestion = ingest_paths(SAMPLES)
    marcus = next(p for p in ingestion.patients if p.family_name == "Chen")
    bundle_dict = build_patient_bundle(marcus.patient_id, ingestion).model_dump(mode="json")
    enc_ref = f"Encounter/{encounter_id_for(marcus.patient_id)}"

    for entry in bundle_dict["entry"]:
        res = entry["resource"]
        if res["resourceType"] == "DocumentReference":
            refs = [e["reference"] for e in res.get("context", {}).get("encounter", [])]
            assert enc_ref in refs
        if res["resourceType"] == "DiagnosticReport":
            assert res.get("encounter", {}).get("reference") == enc_ref


def test_bundle_validation_passes_for_fixture_patients():
    ingestion = ingest_paths(SAMPLES)
    for patient in ingestion.patients:
        bundle = build_patient_bundle(patient.patient_id, ingestion)
        report = validate_bundle(patient.patient_id, bundle)
        assert report.passed, report.to_text()


def test_bundles_persisted_in_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    ingestion = ingest_paths(SAMPLES)
    reports = build_and_store_bundles(ingestion)

    assert len(reports) == len(ingestion.patients)
    assert all(r.passed for r in reports)

    patient_id = ingestion.patients[0].patient_id
    stored = get_bundle(patient_id)
    assert stored is not None
    assert stored["type"] == "collection"
    assert stored["entry"]

    report = get_latest_validation_report(patient_id)
    assert report is not None
    assert report.passed


def test_invalid_bundle_surfaces_error():
    ingestion = ingest_paths(SAMPLES)
    patient = next(p for p in ingestion.patients if p.family_name == "Chen")
    bundle_dict = build_patient_bundle(patient.patient_id, ingestion).model_dump(mode="json")

    assert any(e["resource"]["resourceType"] == "DiagnosticReport" for e in bundle_dict["entry"])

    for entry in bundle_dict["entry"]:
        res = entry.get("resource", {})
        if res.get("resourceType") == "DiagnosticReport":
            res.pop("status", None)

    report = validate_bundle(patient.patient_id, bundle_dict)
    assert not report.passed
    assert any(
        "status" in e.message.lower() and e.resource_type in ("DiagnosticReport", "Bundle")
        for e in report.errors
    )