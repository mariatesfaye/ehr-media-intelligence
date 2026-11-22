import base64
import hashlib
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import chromadb

from ehr_media.config import get_chroma_path
from ehr_media.fhir.store import get_bundle, init_db, list_patient_ids
from ehr_media.summarization.service import summarize_patient

COLLECTION_NAME = "ehr_media"
EMBED_DIM = 384


def _hash_embed(texts: list[str], dim: int = EMBED_DIM) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


def _decode_attachment(data_b64: str) -> str:
    try:
        return base64.b64decode(data_b64).decode("utf-8")
    except Exception:
        return ""


def _patient_name(bundle: dict) -> tuple[str, str]:
    for entry in bundle.get("entry", []):
        res = entry.get("resource") or {}
        if res.get("resourceType") == "Patient":
            names = res.get("name") or [{}]
            given = (names[0].get("given") or ["Unknown"])[0]
            family = names[0].get("family") or "Unknown"
            return given, family
    return "Unknown", "Unknown"


def _chunks_for_patient(patient_id: str, bundle: dict) -> list[dict[str, Any]]:
    given, family = _patient_name(bundle)
    patient_name = f"{given} {family}"
    chunks: list[dict[str, Any]] = []

    for entry in bundle.get("entry", []):
        res = entry.get("resource") or {}
        rtype = res.get("resourceType")
        rid = res.get("id", uuid.uuid4().hex)

        if rtype == "DocumentReference":
            title = (res.get("type") or {}).get("text") or "Document"
            recorded = (res.get("date") or "")[:10]
            parts = [title]
            for content in res.get("content", []):
                data = (content.get("attachment") or {}).get("data")
                if data:
                    parts.append(_decode_attachment(data))
            text = "\n".join(parts)
            chunks.append(
                {
                    "id": f"doc-{rid}",
                    "text": text,
                    "metadata": {
                        "patient_id": patient_id,
                        "patient_name": patient_name,
                        "mrn": patient_id,
                        "resource_type": "DocumentReference",
                        "recorded_at": recorded,
                        "title": title,
                        "resource_id": rid,
                    },
                }
            )

        elif rtype == "DiagnosticReport":
            title = (res.get("code") or {}).get("text") or "Diagnostic report"
            recorded = (res.get("effectiveDateTime") or "")[:10]
            conclusion = res.get("conclusion") or ""
            text = f"{title}\n{conclusion}"
            chunks.append(
                {
                    "id": f"diag-{rid}",
                    "text": text,
                    "metadata": {
                        "patient_id": patient_id,
                        "patient_name": patient_name,
                        "mrn": patient_id,
                        "resource_type": "DiagnosticReport",
                        "recorded_at": recorded,
                        "title": title,
                        "resource_id": rid,
                    },
                }
            )

    summary = summarize_patient(patient_id)
    if summary:
        media_lines = [
            f"{m.type} {m.date}: {m.summary}" for m in summary.recent_media[:6]
        ]
        text = "\n".join(
            [
                summary.narrative,
                f"Chief concern: {summary.chief_concern}",
                "Flagged: " + "; ".join(summary.flagged_anomalies),
                *media_lines,
            ]
        )
        chunks.append(
            {
                "id": f"summary-{patient_id}",
                "text": text,
                "metadata": {
                    "patient_id": patient_id,
                    "patient_name": patient_name,
                    "mrn": patient_id,
                    "resource_type": "Summary",
                    "recorded_at": datetime.now(timezone.utc).date().isoformat(),
                    "title": "AI Summary",
                    "resource_id": f"summary-{patient_id}",
                },
            }
        )

    return chunks


class SearchIndex:
    def __init__(self, chroma_path=None):
        self.chroma_path = chroma_path or get_chroma_path()
        self._embedder = None
        self._collection = None

    def _collection_client(self):
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.chroma_path))
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self._collection_client()
        return self._collection

    @property
    def embedder(self):
        if self._embedder is None:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def embed(self, texts: list[str]) -> list[list[float]]:
        if os.getenv("USE_HASH_EMBEDDINGS", "0") == "1":
            return _hash_embed(texts)
        vectors = self.embedder.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    def rebuild(self, force: bool = False) -> int:
        if force or os.getenv("REBUILD_INDEX", "0") == "1":
            client = chromadb.PersistentClient(path=str(self.chroma_path))
            try:
                client.delete_collection(COLLECTION_NAME)
            except Exception:
                pass
            self._collection = None

        init_db()
        all_chunks: list[dict[str, Any]] = []
        for pid in list_patient_ids():
            bundle = get_bundle(pid)
            if bundle:
                all_chunks.extend(_chunks_for_patient(pid, bundle))

        if not all_chunks:
            return 0

        ids = [c["id"] for c in all_chunks]
        documents = [c["text"] for c in all_chunks]
        metadatas = [c["metadata"] for c in all_chunks]
        embeddings = self.embed(documents)

        batch = 64
        for i in range(0, len(ids), batch):
            self.collection.upsert(
                ids=ids[i : i + batch],
                documents=documents[i : i + batch],
                metadatas=metadatas[i : i + batch],
                embeddings=embeddings[i : i + batch],
            )
        return len(all_chunks)

    def query(
        self,
        query_text: str,
        limit: int = 5,
        resource_types: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        embedding = self.embed([query_text])[0]

        where: dict[str, Any] | None = None
        clauses: list[dict[str, Any]] = []
        if resource_types:
            if len(resource_types) == 1:
                clauses.append({"resource_type": {"$eq": resource_types[0]}})
            else:
                clauses.append({"resource_type": {"$in": resource_types}})
        if len(clauses) == 1:
            where = clauses[0]
        elif len(clauses) > 1:
            where = {"$and": clauses}

        n_results = min(max(limit * 4, 20), 100)
        try:
            result = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
            )
        except Exception:
            if where is not None:
                return []
            result = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
            )

        aggregated: dict[str, dict[str, Any]] = {}
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]

        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] or {}
            recorded = meta.get("recorded_at") or ""
            if date_from and recorded and recorded < date_from:
                continue
            if date_to and recorded and recorded > date_to:
                continue
            if resource_types and meta.get("resource_type") not in resource_types:
                continue
            pid = meta.get("patient_id", "")
            distance = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - float(distance))
            snippet = (documents[i] or "")[:220]

            current = aggregated.get(pid)
            if current is None or score > current["relevance_score"]:
                aggregated[pid] = {
                    "patient_id": pid,
                    "patient_name": meta.get("patient_name", "Unknown"),
                    "mrn": meta.get("mrn", pid),
                    "record_date": meta.get("recorded_at", ""),
                    "resource_type": meta.get("resource_type", "Unknown"),
                    "title": meta.get("title", ""),
                    "relevance_score": round(score, 4),
                    "snippet": snippet,
                    "resource_id": meta.get("resource_id", chunk_id),
                }

        return sorted(aggregated.values(), key=lambda x: x["relevance_score"], reverse=True)[:limit]