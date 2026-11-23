import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ehr_media.api.schemas import (
    PatientResourcesResponse,
    PatientSummaryResponse,
    ResourceListItem,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from ehr_media.fhir.store import get_bundle, init_db
from ehr_media.search.indexer import SearchIndex
from ehr_media.summarization.service import summarize_patient

STATIC_DIR = Path(__file__).resolve().parents[3] / "static"
search_index = SearchIndex()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if search_index.collection.count() == 0:
        search_index.rebuild()
    yield


app = FastAPI(title="EHR Media Intelligence", version="0.1.0", lifespan=lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "indexed_chunks": search_index.collection.count()}


@app.post("/search", response_model=SearchResponse)
def search(body: SearchRequest):
    started = time.perf_counter()
    hits = search_index.query(
        body.query,
        limit=body.limit,
        resource_types=body.resource_types,
        date_from=body.date_from,
        date_to=body.date_to,
    )

    results: list[SearchHit] = []
    for hit in hits:
        summary = summarize_patient(hit["patient_id"])
        summary_snippet = ""
        if summary:
            summary_snippet = summary.narrative[:200]
        elif hit.get("snippet"):
            summary_snippet = hit["snippet"][:200]
        results.append(SearchHit(**hit, summary_snippet=summary_snippet))

    took_ms = (time.perf_counter() - started) * 1000
    return SearchResponse(query=body.query, results=results, took_ms=round(took_ms, 2))


@app.get("/patients/{patient_id}/summary", response_model=PatientSummaryResponse)
def patient_summary(patient_id: str):
    summary = summarize_patient(patient_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Patient summary not found")
    return PatientSummaryResponse(patient_id=patient_id, summary=summary)


@app.get("/patients/{patient_id}/resources", response_model=PatientResourcesResponse)
def patient_resources(patient_id: str):
    bundle = get_bundle(patient_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Patient not found")

    resources: list[ResourceListItem] = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource") or {}
        rtype = res.get("resourceType")
        if rtype not in ("DocumentReference", "DiagnosticReport"):
            continue
        if rtype == "DocumentReference":
            title = (res.get("type") or {}).get("text") or "Document"
            date = (res.get("date") or "")[:10]
        else:
            title = (res.get("code") or {}).get("text") or "Diagnostic report"
            date = (res.get("effectiveDateTime") or "")[:10]
        resources.append(
            ResourceListItem(
                resource_type=rtype,
                resource_id=res.get("id", ""),
                title=title,
                date=date,
            )
        )

    return PatientResourcesResponse(patient_id=patient_id, resources=resources)


@app.get("/")
def index_page():
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {"message": "API running; static UI not found"}