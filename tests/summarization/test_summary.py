from pathlib import Path
from unittest.mock import patch

import pytest

from ehr_media.fhir.store import build_and_store_bundles
from ehr_media.ingestion.service import ingest_paths
from ehr_media.summarization.models import DISCLAIMER, ClinicalSummary, RecentMediaItem
from ehr_media.summarization.service import summarize_all, summarize_patient

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [
    ROOT / "sample_data" / "patients_export.json",
    ROOT / "sample_data" / "scanned_notes.csv",
]


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("USE_MOCK_SUMMARY", "1")
    ingestion = ingest_paths(SAMPLES)
    build_and_store_bundles(ingestion)
    return ingestion


def test_summary_has_required_fields_and_disclaimer(seeded_db):
    patient_id = seeded_db.patients[0].patient_id
    summary = summarize_patient(patient_id)
    assert summary is not None
    assert summary.disclaimer == DISCLAIMER
    assert summary.chief_concern
    assert summary.narrative
    assert summary.confidence in ("low", "medium", "high")
    assert len(summary.narrative.split()) <= 200
    assert isinstance(summary.flagged_anomalies, list)


def test_recent_media_is_structured_list(seeded_db):
    patient_id = next(p.patient_id for p in seeded_db.patients if p.family_name == "Chen")
    summary = summarize_patient(patient_id)
    assert summary is not None
    assert summary.recent_media
    assert all(isinstance(item, RecentMediaItem) for item in summary.recent_media)
    item = summary.recent_media[0]
    assert item.type
    assert item.date
    assert item.summary


def test_cache_prevents_regeneration(seeded_db, monkeypatch):
    from ehr_media.summarization.service import _heuristic_summary

    monkeypatch.setenv("USE_MOCK_SUMMARY", "1")
    patient_id = next(p.patient_id for p in seeded_db.patients if p.family_name == "Chen")

    with patch(
        "ehr_media.summarization.service._heuristic_summary",
        wraps=_heuristic_summary,
    ) as mock_generate:
        first = summarize_patient(patient_id)
        second = summarize_patient(patient_id)

    assert first is not None and second is not None
    assert first.model_dump() == second.model_dump()
    assert mock_generate.call_count == 1


def test_summarize_all_patients(seeded_db):
    summaries = summarize_all()
    assert len(summaries) == len(seeded_db.patients)
    assert all(isinstance(s, ClinicalSummary) for s in summaries.values())


def test_claude_path_invoked_when_api_key_set(seeded_db, monkeypatch):
    monkeypatch.setenv("USE_MOCK_SUMMARY", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    patient_id = next(p.patient_id for p in seeded_db.patients if p.family_name == "Chen")

    expected = ClinicalSummary(
        chief_concern="Chest symptoms",
        key_diagnoses=["possible infection"],
        recent_media=[
            RecentMediaItem(
                type="imaging",
                date="2024-11-01",
                summary="Chest X-ray with mild infiltrate",
            )
        ],
        flagged_anomalies=["Mild infiltrate noted"],
        narrative="Brief clinically grounded summary under two hundred words.",
        confidence="medium",
    )

    with patch("ehr_media.summarization.service._call_claude", return_value=expected) as mock_claude:
        summary = summarize_patient(patient_id)

    mock_claude.assert_called_once()
    assert summary is not None
    assert summary.chief_concern == "Chest symptoms"
    assert summary.disclaimer == DISCLAIMER
    assert summary.recent_media[0].type == "imaging"