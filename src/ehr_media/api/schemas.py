from pydantic import BaseModel, Field

from ehr_media.summarization.models import ClinicalSummary


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_types: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    patient_id: str
    patient_name: str
    mrn: str
    record_date: str
    resource_type: str
    title: str
    relevance_score: float
    snippet: str
    summary_snippet: str = ""


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
    took_ms: float


class ResourceListItem(BaseModel):
    resource_type: str
    resource_id: str
    title: str
    date: str


class PatientSummaryResponse(BaseModel):
    patient_id: str
    summary: ClinicalSummary


class PatientResourcesResponse(BaseModel):
    patient_id: str
    resources: list[ResourceListItem]