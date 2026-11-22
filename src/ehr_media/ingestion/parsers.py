import csv
import json
import uuid
from pathlib import Path
from typing import Any

from ehr_media.models.ir import DocType


MRN_KEYS = ("mrn", "MRN", "medical_record_number", "patient_id", "patientId")
DOB_KEYS = ("dob", "DOB", "birth_date", "birthDate", "date_of_birth")
GENDER_KEYS = ("gender", "sex", "administrative_gender")
GIVEN_KEYS = ("given_name", "first_name", "firstName", "given")
FAMILY_KEYS = ("family_name", "last_name", "lastName", "family", "surname")


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in data and data[k] not in (None, ""):
            return data[k]
    return None


def _parse_doc_type(raw: str | None) -> DocType:
    if not raw:
        return DocType.OTHER
    key = str(raw).strip().lower()
    mapping = {
        "lab": DocType.LAB,
        "labs": DocType.LAB,
        "imaging": DocType.IMAGING,
        "radiology": DocType.IMAGING,
        "discharge": DocType.DISCHARGE,
        "scan": DocType.SCAN,
        "note": DocType.NOTE,
    }
    return mapping.get(key, DocType.OTHER)


def parse_json_export(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)

    patients_raw: list[dict] = []
    documents_raw: list[dict] = []
    findings_raw: list[dict] = []

    if isinstance(payload, list):
        for item in payload:
            if "documents" in item or "media" in item:
                patients_raw.append(item)
            else:
                documents_raw.append(item)
    elif isinstance(payload, dict):
        patients_raw = payload.get("patients", payload.get("Patients", []))
        documents_raw = payload.get("documents", payload.get("media", []))
        findings_raw = payload.get("findings", payload.get("labs", []))

    rows_p: list[dict] = []
    for p in patients_raw:
        ident_list = []
        mrn = _pick(p, MRN_KEYS)
        if mrn:
            ident_list.append({"system": "http://hospital.example/mrn", "value": str(mrn)})
        for alt in p.get("alternate_mrns", p.get("identifiers", [])) or []:
            if isinstance(alt, str):
                ident_list.append({"system": "http://hospital.example/mrn", "value": alt})
            elif isinstance(alt, dict) and alt.get("value"):
                ident_list.append(alt)

        docs = p.get("documents", p.get("media", [])) or []
        for d in docs:
            documents_raw.append({**d, "patient_mrn": mrn or _pick(p, MRN_KEYS)})

        rows_p.append(
            {
                "patient_id": str(mrn or uuid.uuid4().hex[:8]),
                "given_name": _pick(p, GIVEN_KEYS) or p.get("name", {}).get("given", "Unknown"),
                "family_name": _pick(p, FAMILY_KEYS) or p.get("name", {}).get("family", "Unknown"),
                "dob": _pick(p, DOB_KEYS),
                "gender": _pick(p, GENDER_KEYS),
                "identifiers": ident_list,
            }
        )

    rows_d: list[dict] = []
    for d in documents_raw:
        rows_d.append(
            {
                "doc_id": d.get("id", d.get("doc_id", uuid.uuid4().hex)),
                "patient_id": d.get("patient_mrn", d.get("patient_id", d.get("mrn"))),
                "recorded_at": d.get("date", d.get("recorded_at", d.get("doc_date"))),
                "title": d.get("title", "Untitled"),
                "content_text": d.get("body", d.get("content", d.get("text", ""))),
                "source_format": "json",
                "doc_type": _parse_doc_type(d.get("type", d.get("doc_type"))),
            }
        )

    rows_f: list[dict] = []
    for lab in findings_raw:
        rows_f.append(
            {
                "finding_id": lab.get("id", uuid.uuid4().hex),
                "patient_id": lab.get("patient_id", lab.get("mrn")),
                "effective_at": lab.get("effective_at", lab.get("date")),
                "code_display": lab.get("code", lab.get("test_name", "Lab")),
                "conclusion": lab.get("result", lab.get("conclusion", "")),
                "doc_type": DocType.LAB,
            }
        )

    return rows_p, rows_d, rows_f


def parse_csv_notes(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    patients_seen: dict[str, dict] = {}
    documents: list[dict] = []

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return [], [], []

        normalized_headers = {h.strip().lower(): h for h in reader.fieldnames}

        def col(*names: str) -> str | None:
            for n in names:
                if n.lower() in normalized_headers:
                    return normalized_headers[n.lower()]
            return None

        mrn_h = col("mrn", "patient_id")
        name_h = col("patient_name", "name")
        dob_h = col("dob", "birth_date")
        gender_h = col("gender", "sex")
        date_h = col("doc_date", "date", "recorded_at")
        type_h = col("doc_type", "type")
        title_h = col("title")
        body_h = col("body", "content", "note_text")

        for row in reader:
            mrn = row.get(mrn_h or "", "").strip() if mrn_h else ""
            if mrn:
                given, family = "Unknown", "Unknown"
                if name_h and row.get(name_h):
                    parts = str(row[name_h]).strip().split(",", 1)
                    if len(parts) == 2:
                        family, given = parts[0].strip(), parts[1].strip()
                    else:
                        name_parts = str(row[name_h]).split()
                        if len(name_parts) >= 2:
                            given, family = name_parts[0], " ".join(name_parts[1:])
                        else:
                            family = str(row[name_h])

                if mrn not in patients_seen:
                    patients_seen[mrn] = {
                        "patient_id": mrn,
                        "given_name": given,
                        "family_name": family,
                        "dob": row.get(dob_h) if dob_h else None,
                        "gender": row.get(gender_h) if gender_h else None,
                        "identifiers": [{"system": "http://hospital.example/mrn", "value": mrn}],
                    }
                else:
                    existing = patients_seen[mrn]
                    if existing.get("given_name") == "Unknown" and given != "Unknown":
                        existing["given_name"] = given
                    if existing.get("family_name") == "Unknown" and family != "Unknown":
                        existing["family_name"] = family
                    if not existing.get("dob") and dob_h and row.get(dob_h):
                        existing["dob"] = row.get(dob_h)
                    if not existing.get("gender") and gender_h and row.get(gender_h):
                        existing["gender"] = row.get(gender_h)

            body = row.get(body_h or "", "") if body_h else ""
            if not body.strip():
                continue

            documents.append(
                {
                    "doc_id": f"csv-{uuid.uuid4().hex[:12]}",
                    "patient_id": mrn,
                    "recorded_at": row.get(date_h) if date_h else None,
                    "title": row.get(title_h, "Scanned note") if title_h else "Scanned note",
                    "content_text": body,
                    "source_format": "csv",
                    "doc_type": _parse_doc_type(row.get(type_h) if type_h else None),
                }
            )

    return list(patients_seen.values()), documents, []