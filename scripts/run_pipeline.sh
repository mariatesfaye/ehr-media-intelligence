#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python -m ehr_media.fhir_cli
python -m ehr_media.summarization_cli
python -m ehr_media.search_cli
echo "Pipeline complete. Start UI: uvicorn ehr_media.api.main:app --reload"