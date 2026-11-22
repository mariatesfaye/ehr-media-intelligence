import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("USE_MOCK_SUMMARY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [
    ROOT / "sample_data" / "patients_export.json",
    ROOT / "sample_data" / "scanned_notes.csv",
]


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("USE_MOCK_SUMMARY", "1")
    monkeypatch.setenv("USE_HASH_EMBEDDINGS", "1")

    from ehr_media.fhir.store import build_and_store_bundles
    from ehr_media.ingestion.service import ingest_paths
    from ehr_media.api import main as api_main

    ingestion = ingest_paths(SAMPLES)
    build_and_store_bundles(ingestion)

    transport = ASGITransport(app=api_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/health")
        count = api_main.search_index.rebuild(force=True)
        assert count > 0
        yield ac


@pytest.mark.asyncio
async def test_search_returns_ranked_hits(client):
    res = await client.post("/search", json={"query": "troponin elevated", "limit": 5})
    assert res.status_code == 200
    data = res.json()
    assert data["results"]
    assert data["took_ms"] < 2000
    scores = [r["relevance_score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_resource_type_filter(client):
    res = await client.post(
        "/search",
        json={"query": "chest infiltrate", "resource_types": ["DocumentReference"], "limit": 5},
    )
    assert res.status_code == 200
    for hit in res.json()["results"]:
        assert hit["resource_type"] == "DocumentReference"


@pytest.mark.asyncio
async def test_search_date_range_filter(client):
    res = await client.post(
        "/search",
        json={
            "query": "troponin",
            "resource_types": ["DiagnosticReport"],
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
            "limit": 5,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["results"]
    assert any("troponin" in hit["snippet"].lower() or hit["resource_type"] == "DiagnosticReport" for hit in data["results"])
    for hit in data["results"]:
        if hit["record_date"]:
            assert hit["record_date"] >= "2025-01-01"
            assert hit["record_date"] <= "2025-12-31"