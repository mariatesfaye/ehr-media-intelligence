import base64
import uuid
from datetime import datetime, timezone

from fhir.resources.R4B.bundle import Bundle, BundleEntry
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.patient import Patient

from ehr_media.models.ir import DiagnosticFinding, DocType, IngestionResult, MediaDocument, PatientRecord

DOC_TYPE_SYSTEM = "http://loinc.org"
DOC_TYPE_CODES: dict[DocType, tuple[str, str]] = {
    DocType.LAB: ("11502-2", "Laboratory report"),
    DocType.IMAGING: ("18748-4", "Diagnostic imaging study"),
    DocType.DISCHARGE: ("18842-5", "Discharge summary"),
    DocType.SCAN: ("34117-2", "History and physical note"),
    DocType.NOTE: ("34109-9", "Note"),
    DocType.OTHER: ("51848-0", "Clinical attachment"),
}

AMBULATORY_CLASS = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "code": "AMB",
    "display": "ambulatory",
}


def encounter_id_for(patient_id: str) -> str:
    return f"enc-{patient_id}"


def _patient_reference(patient_id: str) -> dict[str, str]:
    return {"reference": f"Patient/{patient_id}"}


def _encounter_reference(patient_id: str) -> dict[str, str]:
    return {"reference": f"Encounter/{encounter_id_for(patient_id)}"}


def _fhir_instant(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def map_patient(record: PatientRecord) -> Patient:
    return Patient(
        id=record.patient_id,
        identifier=[{"system": i.system, "value": i.value} for i in record.identifiers],
        name=[{"family": record.family_name, "given": [record.given_name]}],
        birthDate=record.dob.isoformat() if record.dob else None,
        gender=record.gender.value,
    )


def map_encounter(record: PatientRecord) -> Encounter:
    enc_id = encounter_id_for(record.patient_id)
    return Encounter(
        id=enc_id,
        status="finished",
        class_fhir=AMBULATORY_CLASS,
        subject=_patient_reference(record.patient_id),
    )


def map_document_reference(document: MediaDocument) -> DocumentReference:
    code, display = DOC_TYPE_CODES.get(document.doc_type, DOC_TYPE_CODES[DocType.OTHER])
    payload = base64.b64encode(document.content_text.encode("utf-8")).decode("ascii")
    return DocumentReference(
        id=document.doc_id,
        status="current",
        type={
            "coding": [{"system": DOC_TYPE_SYSTEM, "code": code, "display": display}],
            "text": document.title,
        },
        subject=_patient_reference(document.patient_id),
        context={"encounter": [_encounter_reference(document.patient_id)]},
        date=_fhir_instant(document.recorded_at),
        content=[
            {
                "attachment": {
                    "contentType": "text/plain",
                    "data": payload,
                    "title": document.title,
                }
            }
        ],
    )


def map_diagnostic_report(finding: DiagnosticFinding) -> DiagnosticReport:
    return DiagnosticReport(
        id=finding.finding_id,
        status="final",
        code={"text": finding.code_display},
        subject=_patient_reference(finding.patient_id),
        encounter=_encounter_reference(finding.patient_id),
        effectiveDateTime=_fhir_instant(finding.effective_at),
        conclusion=finding.conclusion,
    )


def build_patient_bundle(patient_id: str, ingestion: IngestionResult) -> Bundle:
    patient = next(p for p in ingestion.patients if p.patient_id == patient_id)
    entries: list[BundleEntry] = [
        BundleEntry(
            fullUrl=f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, patient.patient_id)}",
            resource=map_patient(patient),
        ),
        BundleEntry(
            fullUrl=f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, encounter_id_for(patient_id))}",
            resource=map_encounter(patient),
        ),
    ]

    for document in [d for d in ingestion.documents if d.patient_id == patient_id]:
        entries.append(
            BundleEntry(
                fullUrl=f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, document.doc_id)}",
                resource=map_document_reference(document),
            )
        )

    for finding in [f for f in ingestion.findings if f.patient_id == patient_id]:
        entries.append(
            BundleEntry(
                fullUrl=f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, finding.finding_id)}",
                resource=map_diagnostic_report(finding),
            )
        )

    return Bundle(type="collection", entry=entries)