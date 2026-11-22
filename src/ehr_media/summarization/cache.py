import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ehr_media.config import get_db_path
from ehr_media.fhir.store import init_db
from ehr_media.summarization.models import ClinicalSummary


def get_cached_summary(
    patient_id: str,
    bundle_hash: str,
    db_path: Path | None = None,
) -> ClinicalSummary | None:
    db_path = db_path or get_db_path()
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT summary_json FROM summary_cache
            WHERE patient_id = ? AND bundle_hash = ?
            """,
            (patient_id, bundle_hash),
        ).fetchone()
    if not row:
        return None
    return ClinicalSummary.model_validate_json(row[0])


def put_cached_summary(
    patient_id: str,
    bundle_hash: str,
    summary: ClinicalSummary,
    model: str,
    db_path: Path | None = None,
) -> None:
    db_path = db_path or get_db_path()
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO summary_cache (patient_id, bundle_hash, summary_json, model, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, bundle_hash) DO UPDATE SET
                summary_json = excluded.summary_json,
                model = excluded.model,
                created_at = excluded.created_at
            """,
            (patient_id, bundle_hash, summary.model_dump_json(), model, now),
        )
        conn.commit()