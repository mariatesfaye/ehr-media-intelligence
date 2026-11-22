from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AuditAction(str, Enum):
    FILLED_DEFAULT = "filled_default"
    NORMALIZED = "normalized"
    DEDUPLICATED = "deduplicated"
    MERGED_IDENTIFIER = "merged_identifier"


class AuditEntry(BaseModel):
    field: str
    action: AuditAction
    before: Any | None = None
    after: Any | None = None
    reason: str = ""

    model_config = {"extra": "forbid"}


class RecordAuditLog(BaseModel):
    entries: list[AuditEntry] = Field(default_factory=list)

    def add(self, entry: AuditEntry) -> None:
        self.entries.append(entry)