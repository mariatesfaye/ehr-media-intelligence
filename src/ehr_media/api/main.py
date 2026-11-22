import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ehr_media.api.schemas import SearchHit, SearchRequest, SearchResponse
from ehr_media.fhir.store import init_db
from ehr_media.search.indexer import SearchIndex
from ehr_media.summarization.service import summarize_patient

search_index = SearchIndex()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if search_index.collection.count() == 0:
        search_index.rebuild()
    yield


app = FastAPI(title="EHR Media Intelligence Search", version="0.1.0", lifespan=lifespan)


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