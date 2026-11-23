from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("USE_MOCK_SUMMARY", "1")
    monkeypatch.setenv("USE_HASH_EMBEDDINGS", "1")

    from ehr_media.fhir.store import build_and_store_bundles
    from ehr_media.ingestion.service import ingest_paths
    from ehr_media.api import main as api_main

    ingestion = ingest_paths([ROOT / "sample_data" / "patients_export.json"])
    build_and_store_bundles(ingestion)

    transport = ASGITransport(app=api_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, ingestion


@pytest.mark.asyncio
async def test_patient_summary_and_resources(client):
    ac, ingestion = client
    pid = ingestion.patients[0].patient_id

    summary_res = await ac.get(f"/patients/{pid}/summary")
    assert summary_res.status_code == 200
    body = summary_res.json()
    assert body["patient_id"] == pid
    assert body["summary"]["disclaimer"]
    assert body["summary"]["narrative"]

    resources_res = await ac.get(f"/patients/{pid}/resources")
    assert resources_res.status_code == 200
    resources = resources_res.json()["resources"]
    assert len(resources) >= 1
    assert {r["resource_type"] for r in resources} <= {"DocumentReference", "DiagnosticReport"}