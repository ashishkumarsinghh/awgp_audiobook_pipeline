"""Editorial service shared by command-line entry points.

The manuscript is authoritative. Builds are immutable snapshots; review events
never mutate submitted text/audio. Legacy stage files are migration inputs only.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from difflib import unified_diff
import json
import math
import os
from pathlib import Path
import re
import shutil
import uuid

from src.core.artifacts import atomic_write, write_json
from src.editorial.manuscript import Passage, parse, render, digest, compile_passages
from src.synthesis.runner import synthesize_segments, fingerprint, load_manifest, audio_digest, as_segment
from src.synthesis.assembler import AudioAssembler
from src.synthesis.audio.io import validate_wav, validate_mp3


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default


def now():
    return datetime.now(timezone.utc).isoformat()


def json_hash(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True))


def seconds(value):
    parts = str(value).split(":")
    if len(parts) > 3:
        raise ValueError("Use seconds, mm:ss or hh:mm:ss")
    result = 0.0
    for part in parts:
        number = float(part)
        if not math.isfinite(number) or number < 0:
            raise ValueError("Time must be finite and nonnegative")
        result = result * 60 + number
    return result


def page_label(query):
    """Page shortcuts must not swallow IDs such as p_abc or words like 'peace'."""
    match = re.fullmatch(r"p(\d+|[ivxlcdm]+)", query, re.I)
    if match:
        return match.group(1)
    match = re.fullmatch(r"(?:page\s+|p:)(.+)", query, re.I)
    return match.group(1) if match else None


class PrintedPageMap:
    """Map 1-based PDF scan pages to the labels printed in the book.

    A fixed offset is retained as a backwards-compatible fallback, but a
    project map is preferred because front matter and unnumbered pages make a
    single offset unsafe.
    """

    def __init__(self, rules, overrides=None, fallback_offset=None):
        self.overrides = {int(page): (None if label is None else str(label))
                          for page, label in (overrides or {}).items()}
        self.rules = []
        for rule in rules:
            start = int(rule["pdf_start"])
            end = int(rule["pdf_end"])
            if start < 1 or end < start:
                raise ValueError("page map ranges must be positive and ordered")
            labels = rule.get("printed_labels")
            if labels is not None and (not isinstance(labels, list) or len(labels) != end - start + 1):
                raise ValueError("printed_labels must contain one label per PDF page in the range")
            printed_start = rule.get("printed_start")
            if printed_start is not None:
                printed_start = int(printed_start)
                if printed_start < 1:
                    raise ValueError("printed_start must be positive or null")
            if self.rules and start <= self.rules[-1][1]:
                raise ValueError("page map ranges must not overlap")
            self.rules.append((start, end, printed_start, labels))
        self.fallback_offset = fallback_offset

    def printed_page(self, pdf_page):
        pdf_page = int(pdf_page)
        if pdf_page in self.overrides:
            return self.overrides[pdf_page]
        for start, end, printed_start, labels in self.rules:
            if start <= pdf_page <= end:
                if labels is not None:
                    return None if labels[pdf_page - start] is None else str(labels[pdf_page - start])
                return None if printed_start is None else str(printed_start + pdf_page - start)
        if self.fallback_offset is not None:
            value = pdf_page - int(self.fallback_offset)
            return str(value) if value > 0 else None
        return None

    def as_config(self):
        """Return a stable, JSON-serializable representation of this map."""
        rules = []
        for start, end, printed_start, labels in self.rules:
            rule = {"pdf_start": start, "pdf_end": end}
            if labels is not None:
                rule["printed_labels"] = labels
            else:
                rule["printed_start"] = printed_start
            rules.append(rule)
        return {"version": 1, "rules": rules,
                "overrides": {str(page): label for page, label in sorted(self.overrides.items())}}


def load_printed_page_map(root, page_offset=0):
    """Load a project-specific map, falling back to the legacy offset."""
    candidates = (Path(root) / "page_map.json", Path(root) / ".editorial" / "page_map.json")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return PrintedPageMap([], fallback_offset=page_offset)
    config = read_json(path)
    if not isinstance(config, dict) or not isinstance(config.get("rules"), list):
        raise ValueError(f"{path}: expected an object with a rules array")
    overrides = config.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError(f"{path}: overrides must be an object keyed by PDF page")
    return PrintedPageMap(config["rules"], overrides=overrides, fallback_offset=None)


def save_printed_page_override(root, pdf_page, printed_label):
    """Persist one PDF-page label without destroying an existing map."""
    candidates = (Path(root) / "page_map.json", Path(root) / ".editorial" / "page_map.json")
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[1])
    config = read_json(path, {"version": 1, "rules": [], "overrides": {}})
    if not isinstance(config, dict) or not isinstance(config.get("rules", []), list):
        raise ValueError(f"{path}: expected an object with a rules array")
    overrides = config.setdefault("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError(f"{path}: overrides must be an object keyed by PDF page")
    overrides[str(int(pdf_page))] = None if printed_label is None else str(printed_label)
    write_json(path, config)
    return path


class Workspace:
    def __init__(self, project):
        self.root = Path(project).resolve()
        self.home = self.root / ".editorial"
        self.manuscript = self.root / "manuscript.txt"
        self.home.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self):
        """OS-released lock: crashes do not leave a stale lock file blocking work."""
        with (self.home / "lock").open("a+b") as stream:
            if os.name == "nt":
                import msvcrt
                stream.write(b"0")
                stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise ValueError("An editorial operation is already running for this book") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError("An editorial operation is already running for this book") from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def initialize(self, manager, page_offset=0):
        if self.manuscript.exists():
            return self.manuscript
        def existing(*names):
            return next((self.root / n for n in names if (self.root / n).is_file()), None)
        seg_file = existing("01_segments/segments.json", "03_segments.json")
        phon_file = existing("02_phonetics/phonetics.json", "04_phonetics.json")
        if not seg_file and not phon_file:
            # Run OCR explicitly first for scans; do not incur surprise API calls here.
            text_file = existing("00_ocr/text_cleaned.txt", "02_text_cleaned.txt", "00_ocr/ocr_raw.txt", "01_ocr_raw.txt")
            if not text_file:
                raise ValueError("No transcript yet. Run OCR once: python run.py BOOK 0, then edit.")
            segments = manager.segmenter.segment_text(text_file.read_text(encoding="utf-8"))
            rows = [dict(id=f"p_{uuid.uuid4().hex[:12]}", source_text=s.source_text,
                         page=s.page, segment_type=s.segment_type, pause_after_ms=s.pause_after_ms)
                    for s in segments]
        else:
            rows = read_json(seg_file or phon_file)
        phonetics = {item["id"]: item for item in read_json(phon_file, [])} if phon_file else {}
        page_map = load_printed_page_map(self.root, page_offset)
        passages = []
        for row in rows:
            ph = phonetics.get(row["id"], row)
            if ph.get("source_text") != row.get("source_text"):
                raise ValueError(f"{row['id']}: segments and phonetics disagree on source text; reconcile before import")
            text = row["source_text"]
            speech = ph.get("pronunciation_text", "(inherit)")
            mode = "SSML" if re.search(r"</?[A-Za-z][^>]*>", speech) else "SPEECH"
            if speech == manager.pronunciation.apply(text, context=row.get("segment_type", "prose")):
                speech = "(inherit)"
            pdf = row.get("page")
            printed = page_map.printed_page(pdf) if pdf is not None else None
            page = str(printed) if printed is not None else "?"
            passages.append(Passage(row["id"], text, page, str(pdf) if pdf is not None else "?",
                                    speech, mode, row.get("segment_type", "prose"),
                                    ph.get("pause_after_ms", row.get("pause_after_ms", 600)),
                                    ph.get("rate", "+0%"), ph.get("pitch", "+0Hz"), ph.get("volume", "+0%")))
        if not passages:
            raise ValueError("No passages available for import")
        content = render(passages)
        parse(content)
        atomic_write(self.manuscript, content)
        write_json(self.home / "settings.json", {
            "provider": manager.tts_provider, "voice": manager.tts.voice,
            "speed": manager.profile.mastering_speed, "eq": "smooth", "required_approvals": 2})
        self.save(content)
        # Existing times are offered explicitly as 'legacy', never confused with a new build.
        offsets = existing("04_master/offsets.json")
        if offsets:
            write_json(self.home / "legacy-offsets.json", read_json(offsets))
        return self.manuscript

    def reconcile_pages(self, page_offset=0):
        """Apply the project PDF-to-printed map to the current manuscript."""
        passages = parse(self.manuscript.read_text(encoding="utf-8"))
        page_map = load_printed_page_map(self.root, page_offset)
        changed = 0
        for passage in passages:
            if passage.pdf_page == "?":
                continue
            printed = page_map.printed_page(passage.pdf_page)
            # A map is authoritative.  Do not leave a stale offset-derived
            # label on an explicitly unnumbered or unmapped scan page.
            label = str(printed) if printed is not None else "?"
            if passage.page != label:
                passage.page = label
                changed += 1
        if changed:
            self.save(render(passages))
        return changed

    def intake(self, pdf, manager, *, reocr=False, pages=None, page_offset=0):
        """Explicit OCR/extraction; reruns produce a comparison, never overwrite edits."""
        from src.extract.ocr_engine import extract_text_from_pdf
        source = Path(pdf).resolve()
        if not source.is_file():
            raise ValueError("PDF does not exist")
        if self.manuscript.exists() and not reocr:
            raise ValueError("Manuscript already exists. Use reocr to generate a separate comparison.")
        # Resume a source-bound extraction; a changed PDF gets its own checkpoints.
        source_hash = audio_digest(source)
        folder = self.home / "intake" / source_hash
        if reocr:
            folder = folder / "rerun"
        folder.mkdir(parents=True, exist_ok=True)
        text = extract_text_from_pdf(str(source), checkpoint_dir=str(folder / "checkpoints"),
                                     book_name=self.root.name, pages_to_process=pages, prefer_embedded=not reocr)
        atomic_write(folder / "extracted.txt", text)
        if reocr:
            draft = self.manuscript.read_text(encoding="utf-8") if self.manuscript.exists() else ""
            old = "\n\n".join(f"PDF page {p.pdf_page}\n{p.text}" for p in parse(draft)) if draft else ""
            diff = "".join(unified_diff(old.splitlines(True), text.splitlines(True), fromfile="current manuscript", tofile="new OCR (suggestion only)"))
            atomic_write(folder / "comparison.diff", diff)
            return folder / "comparison.diff"
        target = self.root / "00_scanned.pdf"
        if target.exists() and audio_digest(target) != source_hash:
            raise ValueError("This project already contains a different PDF. Use a different book/project name.")
        if source != target and not target.exists():
            shutil.copy2(source, target)
        atomic_write(self.root / "00_ocr" / "ocr_raw.txt", text)
        write_json(self.home / "source.json", {"sha256": source_hash, "pdf": "00_scanned.pdf", "created_at": now()})
        return self.initialize(manager, page_offset)

    def save(self, content=None, accept_speech=False):
        content = content if content is not None else self.manuscript.read_text(encoding="utf-8")
        passages = parse(content)
        state = read_json(self.home / "draft.json", {})
        previous = {p["id"]: p for p in state.get("passages", [])}
        for p in passages:
            old = previous.get(p.id)
            if (old and p.text != old["text"] and p.speech != "(inherit)"
                    and (p.mode, p.speech) == (old["mode"], old["speech"]) and not accept_speech):
                raise ValueError(f"{p.id}: TEXT changed but its speech override did not. Update it, use (inherit), or validate --accept-speech.")
        revision = digest(content)
        history = self.home / "history"
        history.mkdir(exist_ok=True)
        snapshot = history / f"{revision}.txt"
        if not snapshot.exists():
            atomic_write(snapshot, content)
        if not self.manuscript.exists() or self.manuscript.read_text(encoding="utf-8") != content:
            atomic_write(self.manuscript, content)
        revisions = state.get("revisions", [])
        if not revisions or revisions[-1] != revision:
            revisions.append(revision)
        write_json(self.home / "draft.json", {"revision": revision, "passages": [asdict(p) for p in passages], "revisions": revisions})
        return passages

    def undo(self):
        state = read_json(self.home / "draft.json", {})
        revisions = state.get("revisions", [])
        if not revisions:
            raise ValueError("No saved manuscript history")
        current = self.manuscript.read_text(encoding="utf-8")
        if digest(current) != revisions[-1]:
            target = revisions[-1]
        elif len(revisions) > 1:
            target = revisions[-2]
        else:
            raise ValueError("No earlier revision")
        # Preserve the replaced draft, including invalid edits, for recovery.
        atomic_write(self.home / "history" / f"{digest(current)}.txt", current)
        return self.save((self.home / "history" / f"{target}.txt").read_text(encoding="utf-8"), accept_speech=True)

    def settings(self, **updates):
        value = read_json(self.home / "settings.json", {})
        value.update({k: v for k, v in updates.items() if v is not None})
        speed = float(value.get("speed", 1.15))
        if not math.isfinite(speed) or not 0.5 <= speed <= 2:
            raise ValueError("Final speed must be between 0.5 and 2")
        value["speed"] = speed
        if value.get("eq", "smooth") not in {"smooth", "balanced", "flat"}:
            raise ValueError("Unknown EQ profile")
        if type(value.get("required_approvals", 2)) is not int or value.get("required_approvals", 2) < 1:
            raise ValueError("At least one final approval is required")
        if updates:
            write_json(self.home / "settings.json", value)
        return value

    def version(self, name=None):
        reviews = read_json(self.home / "review.json", {"versions": [], "issues": []})
        if not reviews["versions"]:
            raise ValueError("No submitted version. Build and submit first.")
        name = name or reviews["versions"][-1]["id"]
        result = next((v for v in reviews["versions"] if v["id"] == name), None)
        if not result:
            raise ValueError(f"Unknown submitted version: {name}")
        return result

    def build_record(self, build_id=None):
        build_id = build_id or read_json(self.home / "latest.json", {}).get("build")
        if not build_id or not re.fullmatch(r"[a-f0-9]{64}", build_id):
            raise ValueError("No successful build. Run build first.")
        record = read_json(self.home / "builds" / build_id / "build.json")
        if not record or record.get("status") != "complete":
            raise ValueError("Build is incomplete")
        return record

    def locate(self, query="", version=None):
        passages = parse(self.manuscript.read_text(encoding="utf-8"))
        times = []
        if version == "legacy":
            times = read_json(self.home / "legacy-offsets.json", {}).get("offsets", [])
        elif version:
            record = self.build_record(self.version(version)["build"])
            passages = parse(record["manuscript"])
            times = record["offsets"]
        else:
            latest = read_json(self.home / "latest.json", {})
            if latest:
                record = self.build_record(latest["build"])
                times = record["offsets"]
        query = query.strip()
        if re.fullmatch(r"i\d+", query):
            issue = next((i for i in read_json(self.home / "review.json", {}).get("issues", []) if i["id"] == query), None)
            if not issue:
                return []
            ids = {p.id for p in passages if p.id == issue["passage"] or issue["passage"] in p.parents.split()}
            timing = {item.get("chunk_id", item.get("id")): item for item in times}
            return [{**asdict(p), "score": 1.0, "timing": timing.get(p.id), "reported_version": issue["version"]}
                    for p in passages if p.id in ids]
        page = page_label(query)
        time_match = re.fullmatch(r"\d+:\d{2}(?::\d{2})?(?:\.\d+)?", query)
        if time_match:
            if not times:
                raise ValueError("No timing map. Build first or specify a submitted version.")
            t = seconds(query)
            targets = {item.get("chunk_id", item.get("id")) for item in times if item["start_seconds"] <= t < item["end_seconds"]}
            matches = [(p, 1.0) for p in passages if p.id in targets]
        elif page is not None:
            matches = [(p, 1.0) for p in passages if p.page.casefold() == page.casefold()]
        else:
            exact = [(p, 1.0) for p in passages if not query or query == p.id or query.casefold() in (p.text + "\n" + p.speech).casefold()]
            matches = exact
            if query and not exact:
                from src.qa.roman_feedback import resolve_phrase
                matches = []
                for p in passages:
                    words = p.text.split()
                    width = max(1, len(query.split()))
                    score = max((SequenceMatcher(None, query, " ".join(words[i:i+width])).ratio() for i in range(len(words))), default=0)
                    if query.isascii():
                        score = max(score, (resolve_phrase(query, p.text) or {}).get("score", 0))
                    if score >= 0.55:
                        matches.append((p, score))
                matches.sort(key=lambda pair: pair[1], reverse=True)
                matches = matches[:10]
        timing = {item.get("chunk_id", item.get("id")): item for item in times}
        return [{**asdict(p), "score": round(score, 3), "timing": timing.get(p.id)} for p, score in matches]

    def choose(self, query, version=None):
        matches = self.locate(query, version)
        if len(matches) != 1 or matches[0]["score"] != 1:
            ids = ", ".join(m["id"] for m in matches)
            raise ValueError(f"Choose an exact passage ID from find results; matches: {ids or 'none'}")
        return matches[0]

    def split(self, pid, phrase):
        passages = self.save()
        p = next((p for p in passages if p.id == pid), None)
        if not p or p.text.count(phrase) != 1 or not phrase:
            raise ValueError("Split phrase must occur exactly once in the selected passage")
        if p.speech != "(inherit)":
            raise ValueError("Remove or distribute the speech override before splitting")
        at = p.text.index(phrase)
        if not p.text[:at].strip():
            raise ValueError("Split would leave an empty passage")
        parent = " ".join(dict.fromkeys([p.id, *p.parents.split()]))
        children = [replace(p, id=f"p_{uuid.uuid4().hex[:12]}", text=p.text[:at].strip(), pause=220, parents=parent),
                    replace(p, id=f"p_{uuid.uuid4().hex[:12]}", text=p.text[at:].strip(), parents=parent)]
        index = passages.index(p)
        passages[index:index+1] = children
        return self.save(render(passages))

    def join(self, first, second):
        passages = self.save()
        index = next((i for i, p in enumerate(passages) if p.id == first), -1)
        if index < 0 or index + 1 >= len(passages) or passages[index + 1].id != second:
            raise ValueError("Join requires two adjacent passage IDs in reading order")
        a, b = passages[index:index+2]
        if a.speech != "(inherit)" or b.speech != "(inherit)":
            raise ValueError("Remove or combine speech overrides before joining")
        parent = " ".join(dict.fromkeys([a.id, b.id, *a.parents.split(), *b.parents.split()]))
        passages[index:index+2] = [replace(a, id=f"p_{uuid.uuid4().hex[:12]}", text=a.text + "\n" + b.text,
                                          pause=b.pause, parents=parent)]
        return self.save(render(passages))

    def _compiled(self, manager):
        passages = self.save()
        return compile_passages(passages, manager.pronunciation, manager.tts_provider)

    def _provider_key(self, manager):
        model = getattr(manager.tts, "model", None)
        return manager.tts_provider + (f":{model}" if model else "")

    async def _audio(self, items, manager):
        semaphore = asyncio.Semaphore(3)
        provider = self._provider_key(manager)
        key_locks = {}
        legacy_by_fingerprint = {}
        for old_id, rec in load_manifest(manager.audio_dir).get("chunks", {}).items():
            if rec.get("status") == "complete":
                legacy_by_fingerprint.setdefault(rec.get("fingerprint"), []).append((old_id, rec))
        async def one(item):
            async with semaphore:
                # Use only audible inputs: transcript-only/page/pause edits need no TTS.
                canonical = {**item, "id": "speech", "source_text": item["pronunciation_text"],
                             "normalized_text": item["pronunciation_text"]}
                key = fingerprint(canonical, provider, manager.tts.voice)
                folder = self.home / "cache" / key
                lock = key_locks.setdefault(key, asyncio.Lock())
                async with lock:
                    return await cached(item, canonical, key, folder)

        async def cached(item, canonical, key, folder):
            existed = (folder / "speech.wav").exists()
            # Reuse verified legacy recordings on first migration when their inputs match.
            if not existed and not item.get("take"):
                old_fp = fingerprint(item, manager.tts_provider, manager.tts.voice)
                for old_id, rec in legacy_by_fingerprint.get(old_fp, []):
                    old_path = Path(manager.audio_dir) / f"{old_id}.wav"
                    try:
                        validate_wav(old_path)
                        if audio_digest(old_path) != rec["sha256"]:
                            continue
                    except (OSError, ValueError, KeyError):
                        continue
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(old_path, folder / "speech.wav")
                    write_json(folder / "manifest.json", {"chunks": {"speech": {**rec, "fingerprint": key}}})
                    break
            before = read_json(folder / "manifest.json", {}).get("chunks", {}).get("speech", {})
            await synthesize_segments([canonical], folder, manager.tts, provider)
            rec = load_manifest(folder)["chunks"]["speech"]
            return item["id"], {**rec, "path": str((folder / "speech.wav").relative_to(self.root)),
                                "reused": before.get("status") == "complete" and before.get("sha256") == rec["sha256"]}
        return dict(await asyncio.gather(*(one(item) for item in items)))

    def preview(self, manager, query, context=True):
        target = self.choose(query)
        passages = self.save()
        index = next(i for i, p in enumerate(passages) if p.id == target["id"])
        selected_passages = passages[max(0, index-1):index+2] if context else [passages[index]]
        selected = compile_passages(selected_passages, manager.pronunciation, manager.tts_provider)
        records = asyncio.run(self._audio(selected, manager))
        key = json_hash({"items": selected, "audio": [records[i["id"]]["sha256"] for i in selected], "settings": self.settings()})
        path = self.home / "previews" / f"{key}.mp3"
        path.parent.mkdir(exist_ok=True)
        segments = []
        for item in selected:
            segment = as_segment(item, self.home)
            segment.audio_file = str(self.root / records[item["id"]]["path"])
            segments.append(segment)
        cfg = self.settings()
        AudioAssembler(str(path), speed=cfg["speed"], eq_profile=cfg["eq"]).assemble(segments)
        return path

    def build(self, manager):
        items = self._compiled(manager)
        # A text editor can save while synthesis is running. Build only the
        # validated snapshot, never a mixture of old compiled text and a new file.
        revision = read_json(self.home / "draft.json")["revision"]
        content = (self.home / "history" / f"{revision}.txt").read_text(encoding="utf-8")
        cfg = self.settings()
        inputs = {"manuscript": content, "items": items, "settings": cfg,
                  "provider": self._provider_key(manager), "voice": manager.tts.voice, "compiler": 1}
        bid = json_hash(inputs)
        folder = self.home / "builds" / bid
        folder.mkdir(parents=True, exist_ok=True)
        complete = read_json(folder / "build.json", {})
        if complete.get("status") == "complete":
            self.check_build(complete)
            write_json(self.home / "latest.json", {"build": bid})
            return complete
        write_json(folder / "build.json", {"id": bid, "status": "building", **inputs})
        try:
            records = asyncio.run(self._audio(items, manager))
            audio_dir = folder / "audio"
            audio_dir.mkdir(exist_ok=True)
            cursor, offsets, segments = 0.0, [], []
            for item in items:
                rec = records[item["id"]]
                target = audio_dir / f"{item['id']}.wav"
                shutil.copy2(self.root / rec["path"], target)
                segment = as_segment(item, audio_dir)
                segments.append(segment)
                start = cursor / cfg["speed"]
                cursor += rec["duration_seconds"] + item["pause_after_ms"] / 1000
                offsets.append({"chunk_id": item["id"], "page": item["page"], "pdf_page": item["pdf_page"],
                                "start_seconds": start, "end_seconds": cursor / cfg["speed"],
                                "source_text": item["source_text"]})
            master = folder / "audiobook.mp3"
            AudioAssembler(str(master), speed=cfg["speed"], eq_profile=cfg["eq"]).assemble(segments)
            from src.synthesis.audio.enhancer import AudioEnhancer
            AudioEnhancer.apply_metadata(str(master), str(master), {
                "title": cfg.get("title") or self.root.name,
                "artist": cfg.get("artist") or "AWGP",
                "album": cfg.get("title") or self.root.name, "genre": "Audiobook"})
            validate_mp3(master)
            atomic_write(folder / "manuscript.txt", content)
            write_json(folder / "offsets.json", offsets)
            record = {"id": bid, "status": "complete", "created_at": now(), **inputs,
                      "audio": records, "offsets": offsets, "master_sha256": audio_digest(master),
                      "reused": sum(r["reused"] for r in records.values()), "total": len(items)}
            write_json(folder / "build.json", record)
            write_json(self.home / "latest.json", {"build": bid})
            return record
        except Exception as exc:
            write_json(folder / "build.json", {"id": bid, "status": "failed", **inputs, "error": str(exc)})
            raise

    def check_build(self, record):
        folder = self.home / "builds" / record["id"]
        inputs = {key: record[key] for key in ("manuscript", "items", "settings", "provider", "voice", "compiler")}
        if json_hash(inputs) != record["id"]:
            raise ValueError("Build text/settings integrity mismatch")
        if (folder / "manuscript.txt").read_text(encoding="utf-8") != record["manuscript"]:
            raise ValueError("Build manuscript snapshot integrity mismatch")
        if audio_digest(folder / "audiobook.mp3") != record["master_sha256"]:
            raise ValueError("Build audio integrity mismatch; do not submit or export this build")
        for pid, rec in record["audio"].items():
            if audio_digest(folder / "audio" / f"{pid}.wav") != rec["sha256"]:
                raise ValueError(f"Build passage audio integrity mismatch: {pid}")

    def submit(self, manager):
        record = self.build_record()
        cfg = self.settings()
        current = self._compiled(manager)
        if (record["manuscript"] != self.manuscript.read_text(encoding="utf-8") or record["items"] != current
                or record["settings"] != cfg or record["provider"] != self._provider_key(manager)
                or record["voice"] != manager.tts.voice):
            raise ValueError("Draft or speech settings changed since the build. Build before submitting.")
        self.check_build(record)
        review = read_json(self.home / "review.json", {"versions": [], "issues": []})
        existing = next((v for v in review["versions"] if v["build"] == record["id"]), None)
        if existing:
            from src.editorial.review_pack import create_review_pack
            create_review_pack(self, existing, record)
            return existing
        previous = self.build_record(review["versions"][-1]["build"]) if review["versions"] else None
        old = {i["id"]: i for i in previous["items"]} if previous else {}
        changed = [i["id"] for i in record["items"] if i != old.get(i["id"])
                   or not previous or record["audio"][i["id"]]["sha256"] != previous["audio"].get(i["id"], {}).get("sha256")]
        if previous and (record["settings"] != previous["settings"] or [i["id"] for i in record["items"]] != [i["id"] for i in previous["items"]]):
            changed = [i["id"] for i in record["items"]]
        version = {"id": f"v{len(review['versions'])+1}", "build": record["id"], "created_at": now(),
                   "changed": changed, "removed": [pid for pid in old if pid not in {i['id'] for i in record['items']}], "decisions": {}}
        review["versions"].append(version)
        write_json(self.home / "review.json", review)
        from src.editorial.review_pack import create_review_pack
        create_review_pack(self, version, record)
        return version

    def import_feedback(self, path):
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ValueError("Feedback must be a downloaded review JSON object")
        v = self.version(payload.get("version"))
        if payload.get("build") != v["build"]:
            raise ValueError("Feedback build does not match the submitted version")
        reporter = payload.get("reporter", "")
        notes = payload.get("notes")
        if not isinstance(reporter, str) or not reporter.strip() or not isinstance(notes, list):
            raise ValueError("Feedback requires reporter and notes")
        review = read_json(self.home / "review.json")
        items = {i["id"]: i for i in self.build_record(v["build"])["items"]}
        seen = {i.get("import_key") for i in review["issues"]}
        seen.update(e.get("import_key") for i in review["issues"] for e in i["events"])
        count = 0
        for note in notes:
            if not isinstance(note, dict):
                raise ValueError("Invalid feedback note")
            token = json_hash({"build": v["build"], "reporter": reporter, "note": note})
            if token in seen:
                continue
            if "issue" in note:
                issue = next((i for i in review["issues"] if i["id"] == note["issue"]), None)
                status = note.get("status")
                if not issue or status not in {"verified", "reopened"}:
                    raise ValueError("Unknown issue or review action")
                order = {x["id"]: n for n, x in enumerate(review["versions"])}
                if order[issue["version"]] > order[v["id"]]:
                    raise ValueError("Issue was reported against a later version")
                state = self.issue_status(issue, v)
                if status == "verified" and state["status"] not in {"ready_to_recheck", "reopened"}:
                    raise ValueError(f"{issue['id']}: no changed audio to verify")
                issue["events"].append({"version": v["id"], "status": status, "state": state["state"],
                                        "reviewer": reporter, "note": "Offline review", "at": now(), "import_key": token})
            else:
                item = items.get(note.get("passage"))
                body = note.get("body", "")
                if not item or not isinstance(body, str) or not body.strip():
                    raise ValueError("Feedback note needs a known passage and nonempty comment")
                review["issues"].append({"id": f"i{len(review['issues'])+1}", "version": v["id"],
                    "passage": item["id"], "page": item["page"], "quote": item["source_text"],
                    "timestamp": None, "body": body.strip(), "reporter": reporter, "created_at": now(),
                    "events": [], "import_key": token})
            seen.add(token)
            count += 1
        write_json(self.home / "review.json", review)
        return count

    def issue(self, version, query, body, reporter):
        if not body.strip() or not reporter.strip():
            raise ValueError("Feedback needs a note and reporter name")
        v = self.version(version)
        target = self.choose(query, v["id"])
        review = read_json(self.home / "review.json")
        issue = {"id": f"i{len(review['issues'])+1}", "version": v["id"], "passage": target["id"],
                 "page": target["page"], "quote": target["text"], "timestamp": seconds(query) if ":" in query else None,
                 "body": body, "reporter": reporter, "created_at": now(), "events": []}
        review["issues"].append(issue)
        write_json(self.home / "review.json", review)
        return issue

    def issue_status(self, issue, version):
        record = self.build_record(version["build"])
        original = self.build_record(self.version(issue["version"])["build"])
        targets = [i for i in record["items"] if i["id"] == issue["passage"] or issue["passage"] in i.get("parents", [])]
        old = next(i for i in original["items"] if i["id"] == issue["passage"])
        state = json_hash({"targets": targets, "audio": [record["audio"][i["id"]]["sha256"] for i in targets], "settings": record["settings"]})
        applicable = [e for e in issue["events"] if e["state"] == state]
        if applicable:
            status = applicable[-1]["status"]
        else:
            changed = targets != [old] or record["settings"] != original["settings"]
            if not changed and targets:
                changed = record["audio"][targets[0]["id"]]["sha256"] != original["audio"][old["id"]]["sha256"]
            status = "ready_to_recheck" if changed else "open"
        return {**issue, "status": status, "state": state, "current_passages": [i["id"] for i in targets],
                "current_times": [o for o in record["offsets"] if o["chunk_id"] in {i['id'] for i in targets}]}

    def issues(self, version=None):
        v = self.version(version)
        review = read_json(self.home / "review.json")
        # Later reports are not retroactively attached to an earlier submission.
        eligible = {x["id"] for x in review["versions"][:review["versions"].index(v)+1]}
        return [self.issue_status(i, v) for i in review["issues"] if i["version"] in eligible]

    def resolve(self, issue_id, version, status, reviewer, note=""):
        if status not in {"verified", "reopened", "dismissed"} or not reviewer.strip():
            raise ValueError("Use verified, reopened or dismissed, with a reviewer name")
        if status == "dismissed" and not note.strip():
            raise ValueError("Dismissal requires a reason")
        v = self.version(version)
        review = read_json(self.home / "review.json")
        issue = next((i for i in review["issues"] if i["id"] == issue_id), None)
        eligible = {i["id"]: i for i in self.issues(v["id"])}
        if not issue or issue_id not in eligible:
            raise ValueError("Issue does not exist in this review version")
        state = eligible[issue_id]
        if status == "verified" and state["status"] not in {"ready_to_recheck", "reopened"}:
            raise ValueError("There is no changed audio to verify; dismiss an incorrect report with a reason")
        issue["events"].append({"version": v["id"], "status": status, "state": state["state"],
                                "reviewer": reviewer, "note": note, "at": now()})
        write_json(self.home / "review.json", review)

    def decide(self, version, reviewer, decision, note=""):
        if decision not in {"approved", "changes_requested"} or not reviewer.strip():
            raise ValueError("Decision requires reviewer and approved/changes_requested")
        v = self.version(version)
        if decision == "approved" and any(i["status"] not in {"verified", "dismissed"} for i in self.issues(v["id"])):
            raise ValueError("Unresolved feedback remains for this version")
        review = read_json(self.home / "review.json")
        v = next(i for i in review["versions"] if i["id"] == v["id"])
        v["decisions"][reviewer] = {"decision": decision, "note": note, "at": now()}
        write_json(self.home / "review.json", review)

    def export(self, destination, version=None):
        v = self.version(version)
        record = self.build_record(v["build"])
        decisions = list(v["decisions"].values())
        required = record["settings"].get("required_approvals", 2)
        if (any(d["decision"] == "changes_requested" for d in decisions)
                or sum(d["decision"] == "approved" for d in decisions) < required
                or any(i["status"] not in {"verified", "dismissed"} for i in self.issues(v["id"]))):
            raise ValueError(f"Export requires resolved feedback and {required} current approvals")
        self.check_build(record)
        target = Path(destination).resolve()
        if target.exists():
            raise ValueError("Export destination already exists; choose a new filename")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as out, (self.home / "builds" / record["id"] / "audiobook.mp3").open("rb") as src:
            shutil.copyfileobj(src, out)
        return target
