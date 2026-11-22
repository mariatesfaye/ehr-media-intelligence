import json
from typing import Any

from pydantic import BaseModel, Field

from ehr_media.fhir.mappers import encounter_id_for


class ValidationIssue(BaseModel):
    resource_type: str
    resource_id: str | None = None
    message: str
    path: str | None = None


class ValidationReport(BaseModel):
    patient_id: str
    passed: bool
    errors: list[ValidationIssue] = Field(default_factory=list)

    def to_text(self) -> str:
        if self.passed:
            return f"Patient {self.patient_id}: PASSED"
        lines = [f"Patient {self.patient_id}: FAILED ({len(self.errors)} issue(s))"]
        for issue in self.errors:
            rid = issue.resource_id or "n/a"
            path = issue.path or "n/a"
            lines.append(f"  - [{issue.resource_type}/{rid}] {issue.message} (at {path})")
        return "\n".join(lines)


_RESOURCE_TYPES: dict[str, str] = {
    "Patient": "fhir.resources.R4B.patient.Patient",
    "Encounter": "fhir.resources.R4B.encounter.Encounter",
    "DocumentReference": "fhir.resources.R4B.documentreference.DocumentReference",
    "DiagnosticReport": "fhir.resources.R4B.diagnosticreport.DiagnosticReport",
}


def _validate_resource_dict(resource: dict[str, Any]) -> list[ValidationIssue]:
    import importlib

    rtype = resource.get("resourceType")
    qualname = _RESOURCE_TYPES.get(rtype or "")
    if not qualname:
        return []
    module_path, class_name = qualname.rsplit(".", 1)
    model_cls = getattr(importlib.import_module(module_path), class_name)
    try:
        model_cls.model_validate(resource)
    except Exception as exc:
        return [
            ValidationIssue(
                resource_type=rtype or "Unknown",
                resource_id=resource.get("id"),
                message=str(exc),
                path="resource",
            )
        ]
    return []


def validate_bundle(patient_id: str, bundle: Any) -> ValidationReport:
    """Validate bundle JSON against FHIR R4 models and cross-reference rules."""
    from fhir.resources.R4B.bundle import Bundle

    errors: list[ValidationIssue] = []
    bundle_dict: dict[str, Any] | None = None

    if isinstance(bundle, Bundle):
        bundle_model = bundle
        bundle_dict = json.loads(bundle.model_dump_json())
    else:
        bundle_dict = bundle
        for entry in bundle_dict.get("entry", []):
            res = entry.get("resource")
            if isinstance(res, dict):
                errors.extend(_validate_resource_dict(res))
        try:
            bundle_model = Bundle.model_validate(bundle_dict)
        except Exception as exc:
            errors.append(ValidationIssue(resource_type="Bundle", message=str(exc), path="root"))
            return ValidationReport(patient_id=patient_id, passed=False, errors=errors)

    expected_patient_ref = f"Patient/{patient_id}"
    expected_encounter_ref = f"Encounter/{encounter_id_for(patient_id)}"
    has_encounter = False

    for entry in bundle_model.entry or []:
        resource = entry.resource
        if resource is None:
            errors.append(
                ValidationIssue(
                    resource_type="Unknown",
                    message="Bundle entry is missing resource",
                    path="entry.resource",
                )
            )
            continue

        resource_type = resource.__resource_type__
        resource_id = getattr(resource, "id", None)

        if resource_type == "Encounter":
            has_encounter = True
            if resource_id != encounter_id_for(patient_id):
                errors.append(
                    ValidationIssue(
                        resource_type="Encounter",
                        resource_id=resource_id,
                        message=f"Encounter.id must be {encounter_id_for(patient_id)!r}",
                        path="id",
                    )
                )

        if resource_type in ("DocumentReference", "DiagnosticReport"):
            subject = getattr(resource, "subject", None)
            ref = getattr(subject, "reference", None) if subject else None
            if ref != expected_patient_ref:
                errors.append(
                    ValidationIssue(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        message=f"subject.reference must be {expected_patient_ref}, got {ref!r}",
                        path="subject.reference",
                    )
                )

        if resource_type == "DocumentReference":
            context = getattr(resource, "context", None)
            enc_refs: list[str] = []
            if context and getattr(context, "encounter", None):
                for enc in context.encounter:
                    enc_refs.append(getattr(enc, "reference", None))
            if expected_encounter_ref not in enc_refs:
                errors.append(
                    ValidationIssue(
                        resource_type="DocumentReference",
                        resource_id=resource_id,
                        message=f"context.encounter must include {expected_encounter_ref}",
                        path="context.encounter",
                    )
                )

        if resource_type == "DiagnosticReport":
            encounter = getattr(resource, "encounter", None)
            enc_ref = getattr(encounter, "reference", None) if encounter else None
            if enc_ref != expected_encounter_ref:
                errors.append(
                    ValidationIssue(
                        resource_type="DiagnosticReport",
                        resource_id=resource_id,
                        message=f"encounter.reference must be {expected_encounter_ref}, got {enc_ref!r}",
                        path="encounter.reference",
                    )
                )

    if not has_encounter:
        errors.append(
            ValidationIssue(
                resource_type="Encounter",
                message="Bundle must include an Encounter resource",
                path="entry",
            )
        )

    return ValidationReport(patient_id=patient_id, passed=len(errors) == 0, errors=errors)


def bundle_to_dict(bundle: Any) -> dict[str, Any]:
    return json.loads(bundle.model_dump_json())