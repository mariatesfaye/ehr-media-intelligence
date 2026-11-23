# EHR Media Intelligence Platform

AI-powered pipeline for ingesting heterogeneous EHR media, normalizing to HL7 FHIR R4, generating clinical summaries, and semantic search with a clinician-facing UI.

**Evaluator write-up (≤1 page):** [WRITEUP.md](WRITEUP.md)

## Deliverables checklist

| Deliverable | Status | Location |
|-------------|--------|----------|
| GitHub repo + short write-up | Done | This repo; [WRITEUP.md](WRITEUP.md) |
| One commit per major task (1–5) | See note below | `git log --oneline` |
| README (setup + design) | Done | This file |
| `requirements.txt` / `pyproject.toml` | Done | Repo root |
| Tests via `pytest` | Done | `pytest -q` (18 tests) |
| Tradeoffs | Done | Below + WRITEUP |
| Improvements w/ more time | Done | Below + WRITEUP |
| FHIR / clinical research | Done | Below + WRITEUP |
| AI summary validation | Done | Below + WRITEUP |


## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

| Variable | Purpose |
|----------|---------|
| `DATA_DIR` | SQLite + Chroma path (default `./data`) |
| `ANTHROPIC_API_KEY` | Live Claude summaries |
| `USE_MOCK_SUMMARY=1` | Heuristic summaries (CI/offline) |
| `USE_HASH_EMBEDDINGS=1` | Offline search tests (no MiniLM download) |

## Run end-to-end

```bash
chmod +x scripts/run_pipeline.sh
./scripts/run_pipeline.sh
uvicorn ehr_media.api.main:app --reload
```

Open **http://127.0.0.1:8000/** for the search UI.

Or step-by-step: `ehr-fhir` → `ehr-summarize` → `ehr-index` → `uvicorn`.

## Tests

```bash
pytest -q
```

---

## Architecture (5 tasks)

1. **Ingestion** — JSON + CSV → canonical Pydantic IR with audit logs  
2. **FHIR R4** — `Patient`, synthetic `Encounter`, `DocumentReference`, `DiagnosticReport` bundles in SQLite  
3. **Summarization** — Claude JSON summaries + SQLite cache (`ClinicalSummary` schema)  
4. **Search** — MiniLM + Chroma, `POST /search`, patient-level ranking  
5. **UI** — Vanilla JS + Tailwind CDN, drawer with summary + FHIR resources  

## Design decisions

- **Canonical IR before FHIR** keeps cleaning rules testable and separate from interoperability mapping.
- **Synthetic `Encounter` resources** satisfy assessment linking (`context.encounter`, `DiagnosticReport.encounter`) when source exports lack visit IDs.
- **Per-resource FHIR validation** plus bundle reference checks produce evaluator-readable `ValidationReport` output.
- **Summary cache keyed by bundle hash** avoids redundant LLM spend when ingestion/FHIR output is unchanged.
- **Document-level embedding chunks** with a dedicated **Summary** chunk improve natural-language recall without fragmenting clinical prose.
- **Vanilla JS + Tailwind CDN** minimizes frontend build tooling while meeting responsive and accessibility requirements.

## Tradeoffs

- Tailwind via CDN (not a compiled asset pipeline) to minimize frontend build tooling and focus on the API integration.
- Date filtering applied in application code after vector retrieval for reliable ISO date comparisons with Chroma metadata.
- Heuristic summarization fallback when no API key — sufficient for demos/CI, not for production clinical use.
- Patient-aggregated search results (not per-document cards) prioritize clinician workflow over forensic chunk provenance.

## With more time

- Cross-encoder reranking and chunked embeddings with overlap for long PDFs.
- Real Epic FHIR bulk export / SMART-on-FHIR authentication.
- Human-in-the-loop summary review queue and provenance UI.
- OAuth2, PHI audit logging, and deployment hardening.

## FHIR / clinical concepts researched

- FHIR R4 `DocumentReference.content.attachment` for unstructured narrative text.
- `DiagnosticReport.conclusion` and required cardinality (validated via `fhir.resources` R4B models).
- Encounter `class` (v3-ActCode `AMB`) and reference patterns on clinical resources.
- Administrative gender and LOINC typing for document categories.

## AI summary quality validation

- Mandatory fixed **disclaimer** on every `ClinicalSummary` (Pydantic validator).
- **200-word cap** on `narrative` (validator + prompt).
- System prompt safety rules: no diagnosis from isolated labs, distinguish missing data, no treatment recommendations.
- Manual review on fixture patients for hallucinations; unit tests for schema, cache idempotency, and mock Claude path.
- Offline heuristic path exercised in `pytest` when `USE_MOCK_SUMMARY=1`.