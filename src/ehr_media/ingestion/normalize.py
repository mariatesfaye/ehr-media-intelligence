import re
from datetime import date, datetime

from dateutil import parser as date_parser

from ehr_media.models.audit import AuditAction
from ehr_media.models.ir import Gender


GENDER_MAP: dict[str, Gender] = {
    "m": Gender.MALE,
    "male": Gender.MALE,
    "1": Gender.MALE,
    "f": Gender.FEMALE,
    "female": Gender.FEMALE,
    "2": Gender.FEMALE,
    "o": Gender.OTHER,
    "other": Gender.OTHER,
    "u": Gender.UNKNOWN,
    "unknown": Gender.UNKNOWN,
}


def normalize_mrn(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return ""
    text = str(raw).strip().upper()
    digits = re.sub(r"[^0-9]", "", text)
    if digits:
        return f"MRN-{digits}"
    alnum = re.sub(r"[^A-Z0-9]", "", text)
    return f"MRN-{alnum}" if alnum else ""


def normalize_gender(raw: str | None) -> Gender:
    if not raw:
        return Gender.UNKNOWN
    key = str(raw).strip().lower()
    return GENDER_MAP.get(key, Gender.UNKNOWN)


def parse_date(raw: str | None) -> date | None:
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return date_parser.parse(text, fuzzy=False).date()
    except (ValueError, TypeError):
        return None


def parse_datetime(raw: str | None) -> datetime | None:
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    try:
        return date_parser.parse(text)
    except (ValueError, TypeError):
        return None


def audit_normalize(field: str, before, after, reason: str):
    from ehr_media.models.audit import AuditEntry

    if before == after:
        return None
    return AuditEntry(
        field=field,
        action=AuditAction.NORMALIZED,
        before=before,
        after=str(after) if after is not None else None,
        reason=reason,
    )