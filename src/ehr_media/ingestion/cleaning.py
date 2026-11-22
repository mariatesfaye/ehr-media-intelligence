import hashlib
import re
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from ehr_media.ingestion.normalize import (
    audit_normalize,
    normalize_gender,
    normalize_mrn,
    parse_date,
    parse_datetime,
)
from ehr_media.models.audit import AuditAction, AuditEntry
from ehr_media.models.ir import (
    DiagnosticFinding,
    DocType,
    Gender,
    Identifier,
    IngestionResult,
    MediaDocument,
    PatientRecord,
)


def _content_fingerprint(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip().lower())[:500]
    return hashlib.sha256(collapsed.encode()).hexdigest()


def _pick_richer(base: dict, incoming: dict) -> dict:
    out = {**base}
    for key in ("given_name", "family_name", "dob", "gender"):
        if not out.get(key) and incoming.get(key):
            out[key] = incoming[key]
    idents = list(out.get("identifiers", []))
    seen = {normalize_mrn(str(i.get("value", i) if isinstance(i, dict) else i)) for i in idents}
    for ident in incoming.get("identifiers", []):
        val = normalize_mrn(str(ident.get("value", ident) if isinstance(ident, dict) else ident))
        if val and val not in seen:
            idents.append(ident if isinstance(ident, dict) else {"system": "http://hospital.example/mrn", "value": ident})
            seen.add(val)
    out["identifiers"] = idents
    return out


def _merge_patients_by_identity(raw_patients: list[dict]) -> tuple[list[dict], dict[str, list[AuditEntry]]]:
    """Resolve duplicate patients by canonical MRN, then name+dob."""
    audits: dict[str, list[AuditEntry]] = defaultdict(list)
    by_mrn: dict[str, dict] = {}

    for p in raw_patients:
        pid = normalize_mrn(str(p.get("patient_id", ""))) or str(p.get("patient_id"))
        if pid in by_mrn:
            by_mrn[pid] = _pick_richer(by_mrn[pid], p)
        else:
            by_mrn[pid] = {**p, "patient_id": pid}

    buckets: dict[tuple[str, str, str], list[tuple[str, dict]]] = defaultdict(list)
    for pid, p in by_mrn.items():
        dob_key = str(p.get("dob") or "")
        key = (str(p.get("given_name", "")).lower(), str(p.get("family_name", "")).lower(), dob_key)
        buckets[key].append((pid, p))

    merged: list[dict] = []
    for _, group in buckets.items():
        if len(group) == 1:
            merged.append(group[0][1])
            continue

        primary_pid = sorted(group, key=lambda x: x[0])[0][0]
        combined = group[0][1]
        for alt_pid, row in group[1:]:
            combined = _pick_richer(combined, row)
            if alt_pid != primary_pid:
                audits[f"patient:{primary_pid}"].append(
                    AuditEntry(
                        field="patient_id",
                        action=AuditAction.MERGED_IDENTIFIER,
                        before=alt_pid,
                        after=primary_pid,
                        reason="Merged duplicate patient identity (name+dob match)",
                    )
                )
        combined["patient_id"] = primary_pid
        merged.append(combined)

    return merged, dict(audits)


def clean_ingestion(
    raw_patients: list[dict],
    raw_documents: list[dict],
    raw_findings: list[dict],
) -> IngestionResult:
    merged_patients, merge_audits = _merge_patients_by_identity(raw_patients)
    result = IngestionResult()

    for key, entries in merge_audits.items():
        for e in entries:
            result.log_audit(key, e)

    patient_by_id: dict[str, PatientRecord] = {}

    for raw in merged_patients:
        record_key = f"patient:{raw.get('patient_id', 'unknown')}"
        before_mrn = raw.get("patient_id")
        mrn = normalize_mrn(str(before_mrn or "")) or f"MRN-{uuid.uuid4().hex[:8].upper()}"

        entry = audit_normalize("patient_id", before_mrn, mrn, "Canonical MRN format")
        if entry:
            result.log_audit(record_key, entry)

        dob_before = raw.get("dob")
        dob = parse_date(str(dob_before) if dob_before else None)
        if dob_before and dob:
            entry = audit_normalize("dob", dob_before, dob.isoformat(), "Normalized date format")
            if entry:
                result.log_audit(record_key, entry)
        elif dob_before and not dob:
            result.warnings.append(f"Could not parse DOB for patient {mrn}")
            result.log_audit(
                record_key,
                AuditEntry(
                    field="dob",
                    action=AuditAction.FILLED_DEFAULT,
                    before=dob_before,
                    after=None,
                    reason="Unparseable DOB removed",
                ),
            )

        gender_before = raw.get("gender")
        gender = normalize_gender(str(gender_before) if gender_before else None)
        if not gender_before:
            result.log_audit(
                record_key,
                AuditEntry(
                    field="gender",
                    action=AuditAction.FILLED_DEFAULT,
                    before=None,
                    after=gender.value,
                    reason="Missing gender defaulted to unknown",
                ),
            )

        identifiers: list[Identifier] = []
        seen_vals: set[str] = set()
        for ident in raw.get("identifiers", []):
            val = normalize_mrn(str(ident.get("value", ident) if isinstance(ident, dict) else ident))
            if val and val not in seen_vals:
                seen_vals.add(val)
                system = ident.get("system", "http://hospital.example/mrn") if isinstance(ident, dict) else "http://hospital.example/mrn"
                identifiers.append(Identifier(system=system, value=val))
        if mrn not in seen_vals:
            identifiers.insert(0, Identifier(value=mrn))

        patient = PatientRecord(
            patient_id=mrn,
            given_name=str(raw.get("given_name") or "Unknown"),
            family_name=str(raw.get("family_name") or "Unknown"),
            dob=dob,
            gender=gender,
            identifiers=identifiers,
        )
        patient_by_id[mrn] = patient
        result.patients.append(patient)

    doc_dedupe: dict[tuple[str, str, str, str], MediaDocument] = {}

    for raw in raw_documents:
        pid_raw = raw.get("patient_id")
        pid = normalize_mrn(str(pid_raw or ""))
        if not pid:
            result.warnings.append("Skipping document with no patient_id")
            continue

        if pid not in patient_by_id:
            patient_by_id[pid] = PatientRecord(
                patient_id=pid,
                identifiers=[Identifier(value=pid)],
            )
            result.patients.append(patient_by_id[pid])
            result.log_audit(
                f"patient:{pid}",
                AuditEntry(
                    field="patient",
                    action=AuditAction.FILLED_DEFAULT,
                    before=None,
                    after=pid,
                    reason="Patient created from document reference",
                ),
            )

        record_key = f"document:{raw.get('doc_id', 'new')}"
        dt_before = raw.get("recorded_at")
        recorded_at = parse_datetime(str(dt_before) if dt_before else None) or datetime.utcnow()
        if dt_before:
            entry = audit_normalize("recorded_at", dt_before, recorded_at.isoformat(), "Normalized datetime")
            if entry:
                result.log_audit(record_key, entry)

        doc_type = raw.get("doc_type")
        if isinstance(doc_type, DocType):
            pass
        elif isinstance(doc_type, str):
            try:
                doc_type = DocType(doc_type.lower())
            except ValueError:
                doc_type = DocType.OTHER
        else:
            doc_type = DocType.OTHER

        content = str(raw.get("content_text") or "")
        doc = MediaDocument(
            doc_id=str(raw.get("doc_id", uuid.uuid4().hex)),
            patient_id=pid,
            recorded_at=recorded_at,
            title=str(raw.get("title") or "Untitled"),
            content_text=content,
            source_format=str(raw.get("source_format", "unknown")),
            doc_type=doc_type,
        )

        dedupe_key = (
            pid,
            doc.doc_type.value,
            recorded_at.date().isoformat(),
            _content_fingerprint(content),
        )

        if dedupe_key in doc_dedupe:
            existing = doc_dedupe[dedupe_key]
            if doc.recorded_at > existing.recorded_at:
                doc_dedupe[dedupe_key] = doc
            result.log_audit(
                record_key,
                AuditEntry(
                    field="doc_id",
                    action=AuditAction.DEDUPLICATED,
                    before=doc.doc_id,
                    after=existing.doc_id,
                    reason="Duplicate document content for patient/date/type",
                ),
            )
        else:
            doc_dedupe[dedupe_key] = doc

    result.documents = list(doc_dedupe.values())

    for raw in raw_findings:
        pid = normalize_mrn(str(raw.get("patient_id") or ""))
        if not pid:
            continue
        effective = parse_datetime(str(raw.get("effective_at") or "")) or datetime.utcnow()
        result.findings.append(
            DiagnosticFinding(
                finding_id=str(raw.get("finding_id", uuid.uuid4().hex)),
                patient_id=pid,
                effective_at=effective,
                code_display=str(raw.get("code_display", "Lab")),
                conclusion=str(raw.get("conclusion", "")),
                doc_type=DocType.LAB,
            )
        )

    return result