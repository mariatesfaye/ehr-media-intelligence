import base64
from typing import Any


def extract_bundle_context(bundle: dict[str, Any]) -> dict[str, Any]:
    """Pull human-readable facts from a FHIR bundle for prompts / heuristics."""
    demographics: dict[str, str] = {}
    documents: list[dict[str, str]] = []
    labs: list[dict[str, str]] = []

    for entry in bundle.get("entry", []):
        res = entry.get("resource") or {}
        rtype = res.get("resourceType")
        if rtype == "Patient":
            names = (res.get("name") or [{}])[0]
            given = (names.get("given") or ["Unknown"])[0]
            family = names.get("family") or "Unknown"
            demographics = {
                "name": f"{given} {family}",
                "dob": res.get("birthDate", ""),
                "gender": res.get("gender", ""),
            }
        elif rtype == "DocumentReference":
            title = (res.get("type") or {}).get("text") or "Document"
            body = ""
            for part in res.get("content", []):
                data = (part.get("attachment") or {}).get("data")
                if data:
                    try:
                        body = base64.b64decode(data).decode("utf-8")
                    except Exception:
                        body = ""
            doc_type = "other"
            coding = ((res.get("type") or {}).get("coding") or [{}])[0]
            display = (coding.get("display") or "").lower()
            if "imaging" in display:
                doc_type = "imaging"
            elif "laboratory" in display or "lab" in display:
                doc_type = "lab"
            elif "discharge" in display:
                doc_type = "discharge"
            elif "note" in display or "physical" in display:
                doc_type = "note"
            elif "attachment" in display or "scan" in title.lower():
                doc_type = "scan"
            documents.append(
                {
                    "title": title,
                    "type": doc_type,
                    "date": (res.get("date") or "")[:10],
                    "text": body,
                }
            )
        elif rtype == "DiagnosticReport":
            labs.append(
                {
                    "test": (res.get("code") or {}).get("text", "Lab"),
                    "date": (res.get("effectiveDateTime") or "")[:10],
                    "conclusion": res.get("conclusion") or "",
                }
            )

    return {"demographics": demographics, "documents": documents, "labs": labs}