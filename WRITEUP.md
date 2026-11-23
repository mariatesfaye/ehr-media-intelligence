# EHR Media Intelligence — Project Write-up (≤1 page)

## What we built

A five-stage pipeline: **ingest/clean** heterogeneous JSON and CSV exports → **FHIR R4 bundles** (SQLite) → **Claude clinical summaries** (cached) → **semantic search** (Chroma + MiniLM) → **clinician UI** (Vanilla JS + Tailwind). Sample data and `pytest` cover ingestion edge cases, FHIR validation, summary schema/cache, and search API latency.

## Design decisions

- **Canonical Pydantic IR** between raw files and FHIR keeps cleaning auditable and tests fast.
- **Synthetic `Encounter`** per patient (`enc-{mrn}`) links `DocumentReference.context.encounter` and `DiagnosticReport.encounter` when exports lack visit IDs.
- **Per-resource + reference validation** on bundles; errors surfaced via `ValidationReport.to_text()`.
- **Summaries** structured as `ClinicalSummary` (assessment field names); cache keyed by `patient_id` + bundle hash.
- **Search** indexes document text plus a Summary chunk; results aggregated to top patients for the UI.

## Tradeoffs

| Choice | Why |
|--------|-----|
| Tailwind CDN | No frontend build step; faster submission setup |
| Patient-level search hits | Matches clinician mental model vs. per-chunk cards |
| Post-filter dates after vector query | Reliable ISO date match with Chroma metadata |
| Heuristic summary/embeddings flags | CI and offline demos without API keys / HF downloads |

## With more time

Chunked PDF embeddings + reranker; Epic bulk FHIR integration; human review of AI summaries; OAuth and PHI-grade audit trails.

## FHIR / clinical research

`DocumentReference` attachments for unstructured text; `DiagnosticReport` required fields; Encounter `AMB` class; LOINC document typing; administrative gender for Patient mapping.

## AI summary quality

Fixed disclaimer (Pydantic); 200-word narrative cap; prompt safety (no diagnosis from isolated labs, no treatment advice); fixture review for hallucinations; tests for schema, cache hit, mocked Claude path; `USE_MOCK_SUMMARY=1` in CI.

## How to run

`pip install -e ".[dev]"` → `./scripts/run_pipeline.sh` → `uvicorn ehr_media.api.main:app --reload` → http://127.0.0.1:8000/ → `pytest -q`.

Full detail: [README.md](README.md).