"""Declarative, stage-owned editorial corrections.

Corrections are project data, not edits to generated JSON.  This keeps a
rebuild deterministic and makes the same correction model usable by every
book in the pipeline.
"""
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def load_corrections(project_dir: str) -> Dict[str, Any]:
    path = Path(project_dir) / "project_corrections.json"
    if not path.is_file():
        return {"version": 1, "corrections": []}
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict) or not isinstance(value.get("corrections", []), list):
        raise ValueError(f"Invalid correction file: {path}")
    return value


def matching(correction: Dict[str, Any], item: Dict[str, Any]) -> bool:
    for key in ("page", "paragraph", "segment_type"):
        if key in correction and correction[key] is not None and correction[key] != item.get(key):
            return False
    needle = correction.get("find") or correction.get("find_text")
    return not needle or needle in item.get("source_text", "")


def is_approved(correction: Dict[str, Any]) -> bool:
    """Return whether a correction is allowed to change generated content.

    Destructive/editorial operations are opt-in.  This prevents a reviewer
    suggestion such as removing an introduction from becoming an unnoticed
    deletion during a rebuild.  Existing pronunciation rules remain active
    for backwards compatibility unless explicitly disabled, but new project
    rules can set ``approved: false`` while awaiting review.
    """
    if correction.get("enabled") is False:
        return False
    if correction.get("approved") is not None:
        return bool(correction["approved"])
    if correction.get("kind") in {"exclude", "delete", "remove"}:
        return False
    if correction.get("status") is None and correction.get("stage") == "segment":
        return False
    return correction.get("status", "approved") in {"approved", "applied"}


def corrections_for(stage: str, corrections: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for item in corrections.get("corrections", []):
        if item.get("stage") == stage and is_approved(item):
            yield item


def remove_segments(items: List[Dict[str, Any]], corrections: Dict[str, Any]) -> List[Dict[str, Any]]:
    removals = [rule for rule in corrections_for("segment", corrections)
                if rule.get("kind") in {"exclude", "delete", "remove"}
                or (not rule.get("kind") and not any(k in rule for k in ("replace", "tts_override")))]
    if not removals:
        return items
    return [item for item in items if not any(matching(rule, item) for rule in removals)]


def apply_source_corrections(items: List[Dict[str, Any]], corrections: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply explicitly approved OCR/source corrections to segment text.

    This is intentionally separate from pronunciation aliases.  A source
    correction is allowed only when the project ledger marks it approved and
    scopes it to the segment stage; every replacement is retained in an audit
    record so a rebuild cannot silently change the transcript.
    """
    result = []
    for item in items:
        current = dict(item)
        for rule in corrections_for("segment", corrections):
            if rule.get("kind") not in {"ocr_correction", "source_correction"}:
                continue
            needle = rule.get("find") or rule.get("find_text")
            replacement = rule.get("replace")
            if not needle or replacement is None or not matching(rule, current):
                continue
            before = current.get("source_text", "")
            after = before.replace(needle, replacement)
            if after == before:
                continue
            current["source_text"] = after
            audit = list(current.get("content_correction_audit", []))
            audit.append({
                "stage": "segment",
                "kind": rule.get("kind"),
                "source": needle,
                "replacement": replacement,
                "reason": rule.get("reason", "Approved source correction"),
            })
            current["content_correction_audit"] = audit
        result.append(current)
    return result
