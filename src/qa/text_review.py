"""Pre-TTS text anomaly review.

The deterministic pass is always local and reproducible.  The optional LLM
adapter is deliberately suggestion-only: it may return candidates, but it
cannot mutate source or spoken text without an explicit approval record.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

from src.core.corrections import corrections_for, load_corrections


DEVANAGARI_WORD = re.compile(r"[\u0900-\u097F]+")
KNOWN_OCR_ANOMALIES = {
    "साधिपए": "साधिये",
}


def _issue(code: str, severity: str, item: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {
        "issue_id": hashlib.sha256(
            f"{item.get('id')}:{code}:{item.get('source_text', '')}".encode("utf-8")
        ).hexdigest()[:16],
        "code": code,
        "severity": severity,
        "segment_id": item.get("id"),
        "page": item.get("page"),
        "paragraph": item.get("paragraph"),
        "source_text": item.get("source_text", ""),
        **extra,
    }


def detect_text_anomalies(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find high-signal OCR problems without changing text.

    This intentionally uses a small, explainable rule set.  A language model
    can expand the candidate list later, but deterministic findings remain
    auditable and suitable for CI.
    """
    findings: List[Dict[str, Any]] = []
    for item in items:
        text = item.get("source_text", "")
        for token in DEVANAGARI_WORD.findall(text):
            if token in KNOWN_OCR_ANOMALIES:
                findings.append(_issue(
                    "known_ocr_anomaly", "review", item,
                    token=token, candidate=KNOWN_OCR_ANOMALIES[token],
                    reason="Known checker-confirmed OCR spelling anomaly; approval is required before mutation.",
                ))
        if "[???????]" in text:
            findings.append(_issue("unresolved_ocr", "blocker", item,
                                   reason="OCR contains an unresolved marker."))
        if re.search(r"[ऀ-ॿ]{2,}[A-Za-z]{2,}|[A-Za-z]{2,}[ऀ-ॿ]{2,}", text):
            findings.append(_issue("mixed_script_token", "review", item,
                                   reason="Mixed Latin/Devanagari token may indicate OCR corruption."))
    return findings


class TextReviewLLM(Protocol):
    def suggest(self, *, page_image: Optional[str], source_text: str,
                context: str, language: str) -> List[Dict[str, Any]]: ...


class GeminiTextReviewer:
    """Optional image-grounded reviewer; never called by the normal pipeline."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("Gemini review requires the optional google-genai package.") from exc
        self._types = types
        self.client = genai.Client()
        self.model = model

    def suggest(self, *, page_image: Optional[str], source_text: str,
                context: str, language: str) -> List[Dict[str, Any]]:
        contents: List[Any] = [build_llm_prompt(source_text, context, language)]
        if page_image:
            image_path = Path(page_image)
            contents.append(self._types.Part.from_bytes(
                data=image_path.read_bytes(),
                mime_type="image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png",
            ))
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=self._types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        value = json.loads(response.text or "[]")
        return value if isinstance(value, list) else []


def build_llm_prompt(source_text: str, context: str, language: str) -> str:
    return (
        "You are a conservative Hindi/Sanskrit OCR reviewer. Return JSON candidates only. "
        "Do not rewrite style, meaning, names, quotations, or Sanskrit. Every candidate "
        "must cite visible page evidence or return an empty list. Keep source text unchanged.\n"
        f"language={language}\ncontext={context}\nsource={source_text}"
    )


def run_text_review(project_dir: str, *, llm: Optional[TextReviewLLM] = None,
                    page_images: Optional[Dict[Any, str]] = None,
                    segments_file: Optional[str] = None) -> Dict[str, Any]:
    root = Path(project_dir)
    segments_path = Path(segments_file) if segments_file else root / "01_segments" / "segments.json"
    items = json.loads(segments_path.read_text(encoding="utf-8"))
    deterministic = detect_text_anomalies(items)
    llm_suggestions: List[Dict[str, Any]] = []
    if llm is not None:
        for item in items:
            suggestions = llm.suggest(
                page_image=(page_images or {}).get(item.get("page")),
                source_text=item.get("source_text", ""),
                context="neighboring segment review is supplied by the caller",
                language="Hindi/Sanskrit-uncertain",
            )
            for suggestion in suggestions:
                llm_suggestions.append({
                    "segment_id": item.get("id"), "page": item.get("page"),
                    "source_text": item.get("source_text", ""),
                    "status": "candidate_requires_human_approval",
                    **suggestion,
                })
    report = {
        "version": 1,
        "project": root.name,
        "status": "review_required" if deterministic or llm_suggestions else "pass",
        "deterministic_findings": deterministic,
        "llm_suggestions": llm_suggestions,
        "llm_invoked": llm is not None,
        "mutation_policy": "No source or spoken text is changed by this report.",
    }
    target = root / "07_qa" / "text_review.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
