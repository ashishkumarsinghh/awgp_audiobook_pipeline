"""Readable, authoritative manuscripts. Generated pipeline JSON is never edited."""
from dataclasses import dataclass, field
import hashlib
import re
import xml.etree.ElementTree as ET

from src.core.artifacts import validate_segments


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class Passage:
    id: str
    text: str
    page: str = "?"
    pdf_page: str = "?"
    speech: str = "(inherit)"
    mode: str = "SPEECH"
    kind: str = "prose"
    pause: int = 600
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    take: int = 0
    parents: str = ""
    line: int = field(default=1, compare=False)


def render(passages):
    header = ("# Audiobook manuscript v1\n"
              "# Edit TEXT for book corrections. SPEECH: (inherit) follows TEXT.\n"
              "# Use SPEECH for a spoken override or SSML for supported XML.\n"
              "# PAGE is the printed label; PDF_PAGE is the 1-based scan position.\n"
              "# Keep passage IDs. Use split/join commands to preserve feedback links.\n"
              "# Increment TAKE to request a fresh recording with unchanged text.\n\n")
    blocks = []
    for p in passages:
        blocks.append(f"=== Passage {p.id} ===\n"
                      f"PAGE: {p.page}\nPDF_PAGE: {p.pdf_page}\nTYPE: {p.kind}\n"
                      f"PAUSE_AFTER_MS: {p.pause}\nRATE: {p.rate}\nPITCH: {p.pitch}\n"
                      f"VOLUME: {p.volume}\nTAKE: {p.take}\nPARENTS: {p.parents}\n\n"
                      f"TEXT:\n{p.text}\n\n{p.mode}:\n{p.speech}\n")
    return header + "\n".join(blocks)


def parse(content):
    markers = list(re.finditer(r"^=== Passage ([A-Za-z0-9_-]{1,80}) ===\s*$", content, re.M))
    if not markers:
        raise ValueError("manuscript.txt: no passage headers found")
    preamble = content[:markers[0].start()]
    if any(line.strip() and not line.startswith("#") for line in preamble.splitlines()):
        raise ValueError("manuscript.txt: unexpected content before first passage")
    passages, seen = [], set()
    allowed = {"PAGE", "PDF_PAGE", "TYPE", "PAUSE_AFTER_MS", "RATE", "PITCH", "VOLUME", "TAKE", "PARENTS"}
    for n, marker in enumerate(markers):
        pid = marker.group(1)
        line = content[:marker.start()].count("\n") + 1
        where = f"manuscript.txt:{line} ({pid})"
        if pid in seen:
            raise ValueError(f"{where}: duplicate passage ID")
        seen.add(pid)
        body = content[marker.end():markers[n + 1].start() if n + 1 < len(markers) else len(content)]
        if "=== Passage" in body:
            raise ValueError(f"{where}: malformed passage header")
        sections = list(re.finditer(r"^(TEXT|SPEECH|SSML):\s*$", body, re.M))
        if len(sections) != 2 or sections[0].group(1) != "TEXT" or sections[1].group(1) not in {"SPEECH", "SSML"}:
            raise ValueError(f"{where}: expected TEXT followed by exactly one SPEECH or SSML section")
        meta = {}
        for entry in body[:sections[0].start()].splitlines():
            if not entry.strip():
                continue
            key, sep, value = entry.partition(":")
            if not sep or key not in allowed or key in meta:
                raise ValueError(f"{where}: unknown or duplicate field {key!r}")
            meta[key] = value.strip()
        try:
            p = Passage(pid, body[sections[0].end():sections[1].start()].strip(),
                        page=meta.get("PAGE", "?"), pdf_page=meta.get("PDF_PAGE", "?"),
                        speech=body[sections[1].end():].strip(), mode=sections[1].group(1),
                        kind=meta.get("TYPE", "prose"), pause=int(meta.get("PAUSE_AFTER_MS", 600)),
                        rate=meta.get("RATE", "+0%"), pitch=meta.get("PITCH", "+0Hz"),
                        volume=meta.get("VOLUME", "+0%"), take=int(meta.get("TAKE", 0)),
                        parents=meta.get("PARENTS", ""), line=line)
            if p.take < 0 or not p.speech or not p.page:
                raise ValueError("TAKE must be nonnegative; PAGE and speech must be nonempty")
            if p.pdf_page != "?" and (not p.pdf_page.isdigit() or int(p.pdf_page) < 1):
                raise ValueError("PDF_PAGE must be a positive integer or ?")
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", parent) for parent in p.parents.split()):
                raise ValueError("invalid PARENTS identifiers")
            # Unresolved OCR must remain editable; compilation blocks synthesis.
            validate_segments([{"id": p.id, "source_text": p.text.replace("[अस्पष्ट]", "?"), "pause_after_ms": p.pause,
                                "rate": p.rate, "pitch": p.pitch, "volume": p.volume}])
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
        passages.append(p)
    return passages


def validate_ssml(text, provider):
    # Only adapters with real SSML transport may receive authored markup.
    if provider not in {"google", "gcloud", "gemini", "azure"}:
        raise ValueError(f"{provider} does not accept authored SSML in this pipeline; use SPEECH or choose Google/Azure")
    if re.search(r"<!|<\?", text):
        raise ValueError("SSML declarations, entities, and processing instructions are not allowed")
    try:
        root = ET.fromstring(text if text.lstrip().startswith("<speak") else f"<speak>{text}</speak>")
    except ET.ParseError as exc:
        raise ValueError(f"Malformed SSML: {exc}") from exc
    tags = {"speak", "p", "s", "break", "prosody", "phoneme", "sub", "say-as", "emphasis"}
    attrs = {"speak": {"version", "lang"}, "p": set(), "s": set(),
             "break": {"time", "strength"}, "prosody": {"rate", "pitch", "volume"},
             "phoneme": {"alphabet", "ph"}, "sub": {"alias"},
             "say-as": {"interpret-as", "format", "detail"}, "emphasis": {"level"}}
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in tags:
            raise ValueError(f"Unsupported SSML element: {tag}")
        unknown = {key.split("}")[-1] for key in node.attrib} - attrs[tag]
        if unknown:
            raise ValueError(f"Unsupported SSML attributes on {tag}: {', '.join(sorted(unknown))}")
    if root.tag.split("}")[-1] != "speak" or not "".join(root.itertext()).strip():
        raise ValueError("SSML needs a speak root and spoken text")
    return text


def compile_passages(passages, pronunciation, provider):
    data = []
    for p in passages:
        supported = {"edge": {"rate", "pitch", "volume"}, "azure": {"rate", "pitch", "volume"},
                     "google": {"rate"}, "gcloud": {"rate"}, "gemini": {"rate"},
                     "sarvam": {"rate"}, "sarvamai": {"rate"}, "sarvam-ai": {"rate"}}
        for key, default in (("rate", "+0%"), ("pitch", "+0Hz"), ("volume", "+0%")):
            if getattr(p, key) != default and key not in supported.get(provider, set()):
                raise ValueError(f"{p.id}: the {provider} adapter does not implement {key}; reset it to {default} or use a supported provider/SSML instruction")
        if "[???????]" in p.text:
            raise ValueError(f"{p.id}: resolve the OCR marker against the PDF before generating")
        speech = pronunciation.apply(p.text, context=p.kind) if p.speech == "(inherit)" else p.speech
        if p.mode == "SSML":
            validate_ssml(speech, provider)
            if not speech.lstrip().startswith("<speak"):
                speech = f"<speak>{speech}</speak>"
        elif re.search(r"</?[A-Za-z][^>]*>", speech):
            raise ValueError(f"{p.id}: put XML in an SSML section, not SPEECH")
        data.append({"id": p.id, "source_text": p.text, "normalized_text": p.text,
                     "pronunciation_text": speech, "segment_type": p.kind,
                     "page": p.page, "pdf_page": p.pdf_page, "parents": p.parents.split(),
                     "rate": p.rate, "pitch": p.pitch, "volume": p.volume,
                     "pause_before_ms": 0, "pause_after_ms": p.pause, "take": p.take})
    return validate_segments(data)
