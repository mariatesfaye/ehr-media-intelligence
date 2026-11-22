from typing import Literal

from pydantic import BaseModel, Field, field_validator

DISCLAIMER = (
    "This summary is AI-generated from available EHR media records and is not a clinical decision."
)


class RecentMediaItem(BaseModel):
    type: str
    date: str
    summary: str


class ClinicalSummary(BaseModel):
    chief_concern: str = ""
    key_diagnoses: list[str] = Field(default_factory=list)
    recent_media: list[RecentMediaItem] = Field(default_factory=list)
    flagged_anomalies: list[str] = Field(default_factory=list)
    narrative: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    disclaimer: str = DISCLAIMER

    @field_validator("narrative")
    @classmethod
    def narrative_max_200_words(cls, value: str) -> str:
        words = value.split()
        if len(words) > 200:
            return " ".join(words[:200])
        return value

    @field_validator("disclaimer")
    @classmethod
    def force_disclaimer(cls, value: str) -> str:
        return DISCLAIMER