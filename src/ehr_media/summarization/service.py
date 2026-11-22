import json
import os
import re
from typing import Any

from ehr_media.fhir.store import (
    content_hash,
    get_bundle,
    get_bundle_content_hash,
    list_patient_ids,
)
from ehr_media.summarization.bundle_text import extract_bundle_context
from ehr_media.summarization.cache import get_cached_summary, put_cached_summary
from ehr_media.summarization.models import DISCLAIMER, ClinicalSummary, RecentMediaItem
from ehr_media.summarization.prompts import SYSTEM_PROMPT, build_user_prompt

_ANOMALY_KEYWORDS = ("elevated", "abnormal", "above reference", "infiltrate", "hyponatremia", "exacerbation")


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _infer_confidence(doc_count: int, lab_count: int) -> str:
    total = doc_count + lab_count
    if total >= 4:
        return "high"
    if total >= 1:
        return "medium"
    return "low"


def _heuristic_summary(patient_id: str, bundle: dict[str, Any]) -> ClinicalSummary:
    ctx = extract_bundle_context(bundle)
    texts: list[str] = []
    flagged_anomalies: list[str] = []
    recent_media: list[RecentMediaItem] = []

    for doc in ctx["documents"]:
        snippet = doc["text"][:180] if doc["text"] else doc["title"]
        recent_media.append(
            RecentMediaItem(
                type=doc.get("type", "other"),
                date=doc["date"] or "unknown",
                summary=snippet,
            )
        )
        if doc["text"]:
            texts.append(doc["text"])
            lower = doc["text"].lower()
            if any(k in lower for k in _ANOMALY_KEYWORDS):
                flagged_anomalies.append(f"{doc['title']}: {doc['text'][:140]}")

    for lab in ctx["labs"]:
        conclusion = lab["conclusion"] or ""
        recent_media.append(
            RecentMediaItem(
                type="lab",
                date=lab["date"] or "unknown",
                summary=conclusion[:180] or lab["test"],
            )
        )
        if conclusion:
            texts.append(conclusion)
            if any(k in conclusion.lower() for k in _ANOMALY_KEYWORDS):
                flagged_anomalies.append(f"{lab['test']}: {conclusion[:140]}")

    chief = texts[0][:200] if texts else "No clinical narrative available in stored media."
    narrative = " ".join(texts).strip()
    if _word_count(narrative) > 200:
        narrative = " ".join(narrative.split()[:200])

    diagnoses: list[str] = []
    for text in texts:
        if "asthma" in text.lower() and "asthma exacerbation" not in diagnoses:
            diagnoses.append("asthma exacerbation (documented)")
        if "troponin" in text.lower() and "elevated troponin (documented)" not in diagnoses:
            diagnoses.append("elevated troponin (documented)")

    return ClinicalSummary(
        chief_concern=chief,
        key_diagnoses=diagnoses,
        recent_media=recent_media[:8],
        flagged_anomalies=flagged_anomalies[:6],
        narrative=narrative or chief,
        disclaimer=DISCLAIMER,
        confidence=_infer_confidence(len(ctx["documents"]), len(ctx["labs"])),
    )


def _call_claude(patient_id: str, bundle: dict[str, Any]) -> ClinicalSummary:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    message = client.messages.create(
        model=model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(patient_id, bundle)}],
    )
    raw = message.content[0].text
    start = raw.find("{")
    end = raw.rfind("}")
    payload = json.loads(raw[start : end + 1])
    summary = ClinicalSummary.model_validate(payload)
    summary.disclaimer = DISCLAIMER
    return summary


def _should_use_mock() -> bool:
    return os.getenv("USE_MOCK_SUMMARY", "0") == "1" or not os.getenv("ANTHROPIC_API_KEY")


def summarize_patient(patient_id: str) -> ClinicalSummary | None:
    bundle = get_bundle(patient_id)
    if not bundle:
        return None

    digest = get_bundle_content_hash(patient_id) or content_hash(bundle)
    cached = get_cached_summary(patient_id, digest)
    if cached:
        return cached

    if _should_use_mock():
        summary = _heuristic_summary(patient_id, bundle)
        model_name = "heuristic-mock"
    else:
        try:
            summary = _call_claude(patient_id, bundle)
            model_name = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        except Exception:
            summary = _heuristic_summary(patient_id, bundle)
            model_name = "heuristic-fallback"

    put_cached_summary(patient_id, digest, summary, model_name)
    return summary


def summarize_all() -> dict[str, ClinicalSummary]:
    summaries: dict[str, ClinicalSummary] = {}
    for patient_id in list_patient_ids():
        summary = summarize_patient(patient_id)
        if summary:
            summaries[patient_id] = summary
    return summaries