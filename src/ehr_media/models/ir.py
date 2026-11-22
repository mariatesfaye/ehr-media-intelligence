from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from ehr_media.models.audit import AuditEntry, RecordAuditLog


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class DocType(str, Enum):
    LAB = "lab"
    IMAGING = "imaging"
    DISCHARGE = "discharge"
    SCAN = "scan"
    NOTE = "note"
    OTHER = "other"


class Identifier(BaseModel):
    system: str = "http://hospital.example/mrn"
    value: str


class PatientRecord(BaseModel):
    patient_id: str
    given_name: str = "Unknown"
    family_name: str = "Unknown"
    dob: date | None = None
    gender: Gender = Gender.UNKNOWN
    identifiers: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def dob_not_future(self) -> "PatientRecord":
        if self.dob and self.dob > date.today():
            raise ValueError("date of birth cannot be in the future")
        return self


class MediaDocument(BaseModel):
    doc_id: str
    patient_id: str
    recorded_at: datetime
    title: str = "Untitled"
    content_text: str
    source_format: str
    doc_type: DocType = DocType.OTHER


class DiagnosticFinding(BaseModel):
    finding_id: str
    patient_id: str
    effective_at: datetime
    code_display: str
    conclusion: str
    doc_type: DocType = DocType.LAB


class IngestionResult(BaseModel):
    patients: list[PatientRecord] = Field(default_factory=list)
    documents: list[MediaDocument] = Field(default_factory=list)
    findings: list[DiagnosticFinding] = Field(default_factory=list)
    audit_logs: dict[str, RecordAuditLog] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def audit_for(self, record_key: str) -> RecordAuditLog:
        if record_key not in self.audit_logs:
            self.audit_logs[record_key] = RecordAuditLog()
        return self.audit_logs[record_key]

    def log_audit(self, record_key: str, entry: AuditEntry) -> None:
        self.audit_for(record_key).add(entry)