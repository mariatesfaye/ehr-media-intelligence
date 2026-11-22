import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ehr_media.config import get_db_path
from ehr_media.fhir.mappers import build_patient_bundle
from ehr_media.fhir.validation import ValidationReport, bundle_to_dict, validate_bundle
from ehr_media.models.ir import IngestionResult


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    db_path = db_path or get_db_path()
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS fhir_bundles (
                patient_id TEXT PRIMARY KEY,
                bundle_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                validated_at TEXT NOT NULL,
                validation_passed INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS validation_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS summary_cache (
                patient_id TEXT NOT NULL,
                bundle_hash TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (patient_id, bundle_hash)
            );
            """
        )


def content_hash(bundle_dict: dict[str, Any]) -> str:
    canonical = json.dumps(bundle_dict, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_and_store_bundles(
    ingestion: IngestionResult,
    db_path: Path | None = None,
) -> list[ValidationReport]:
    """Map ingestion output to per-patient FHIR Bundles, validate, and persist."""
    db_path = db_path or get_db_path()
    init_db(db_path)
    reports: list[ValidationReport] = []
    timestamp = datetime.now(timezone.utc).isoformat()

    with _connect(db_path) as conn:
        for patient in ingestion.patients:
            bundle = build_patient_bundle(patient.patient_id, ingestion)
            bundle_dict = bundle_to_dict(bundle)
            report = validate_bundle(patient.patient_id, bundle)
            reports.append(report)
            digest = content_hash(bundle_dict)

            conn.execute(
                """
                INSERT INTO fhir_bundles (patient_id, bundle_json, content_hash, validated_at, validation_passed)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET
                    bundle_json = excluded.bundle_json,
                    content_hash = excluded.content_hash,
                    validated_at = excluded.validated_at,
                    validation_passed = excluded.validation_passed
                """,
                (patient.patient_id, json.dumps(bundle_dict), digest, timestamp, int(report.passed)),
            )
            conn.execute(
                """
                INSERT INTO validation_reports (patient_id, report_json, created_at)
                VALUES (?, ?, ?)
                """,
                (patient.patient_id, report.model_dump_json(), timestamp),
            )
        conn.commit()

    return reports


def list_patient_ids(db_path: Path | None = None) -> list[str]:
    db_path = db_path or get_db_path()
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT patient_id FROM fhir_bundles ORDER BY patient_id").fetchall()
    return [row["patient_id"] for row in rows]


def get_bundle_content_hash(patient_id: str, db_path: Path | None = None) -> str | None:
    db_path = db_path or get_db_path()
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content_hash FROM fhir_bundles WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
    return row["content_hash"] if row else None


def get_bundle(patient_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    db_path = db_path or get_db_path()
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT bundle_json FROM fhir_bundles WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
    return json.loads(row["bundle_json"]) if row else None


def get_latest_validation_report(patient_id: str, db_path: Path | None = None) -> ValidationReport | None:
    db_path = db_path or get_db_path()
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT report_json FROM validation_reports
            WHERE patient_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id,),
        ).fetchone()
    if not row:
        return None
    return ValidationReport.model_validate_json(row["report_json"])


def print_validation_summary(reports: list[ValidationReport]) -> None:
    for report in reports:
        print(report.to_text())