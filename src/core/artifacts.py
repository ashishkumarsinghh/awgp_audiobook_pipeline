"""Atomic project artifacts and validation shared by CLI and API stages."""
import json
import os
import re
import tempfile
from pathlib import Path


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def validate_segments(data):
    if not isinstance(data, list) or not data:
        raise ValueError("No narration segments. Review the OCR text and run segmentation first.")
    seen = set()
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Segment {index} must be an object.")
        chunk_id = item.get("id", "")
        if not isinstance(chunk_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", chunk_id):
            raise ValueError(f"Segment {index} has an invalid ID. Use letters, digits, underscores or dashes.")
        if chunk_id in seen:
            raise ValueError(f"Duplicate segment ID: {chunk_id}.")
        seen.add(chunk_id)
        for field in ("source_text", "normalized_text", "pronunciation_text"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"{chunk_id}: {field} must be text.")
        if not item.get("source_text", "").strip():
            raise ValueError(f"{chunk_id}: source text is empty.")
        if "pronunciation_text" in item and not item["pronunciation_text"].strip():
            raise ValueError(f"{chunk_id}: pronunciation text is empty.")
        if any("[अस्पष्ट]" in item.get(field, "") for field in ("source_text", "normalized_text", "pronunciation_text")):
            raise ValueError(f"{chunk_id}: unresolved OCR marker [अस्पष्ट]. Compare this passage with the PDF before generating narration.")
        for field in ("pause_before_ms", "pause_after_ms"):
            value = item.get(field, 0)
            if type(value) is not int or not 0 <= value <= 30000:
                raise ValueError(f"{chunk_id}: {field} must be between 0 and 30000 milliseconds.")
        for field, pattern, default in (("rate", r"[+-][0-9]+%", "+0%"), ("pitch", r"[+-][0-9]+Hz", "+0Hz"), ("volume", r"[+-][0-9]+%", "+0%")):
            if not isinstance(item.get(field, default), str) or not re.fullmatch(pattern, item.get(field, default)):
                raise ValueError(f"{chunk_id}: invalid {field}.")
    return data


def read_segments(path):
    with open(path, encoding="utf-8") as stream:
        return validate_segments(json.load(stream))
