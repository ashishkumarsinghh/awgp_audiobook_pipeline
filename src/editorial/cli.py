"""Short commands over the editorial service; no interactive correction wizard."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from src.core.artifacts import write_json
from src.editorial.manuscript import parse, render
from src.editorial.workspace import Workspace, read_json, seconds, page_label, save_printed_page_override


COMMANDS = {"edit", "find", "play", "preview", "build", "submit", "feedback", "issues",
            "verify", "reopen", "dismiss", "approve", "request-changes", "deliver", "validate",
            "undo", "split", "join", "settings", "page-map", "reconcile-pages", "pdf", "take", "history", "import", "reocr"}


def handles(argv):
    return bool(argv) and (argv[0] in COMMANDS or (len(argv) > 1 and argv[1] in COMMANDS))


def editor_command(path, line):
    template = os.environ.get("AUDIOBOOK_EDITOR") or os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if template:
        parts = shlex.split(template)
        if any("{file}" in part or "{line}" in part for part in parts):
            return [part.replace("{file}", str(path)).replace("{line}", str(line)) for part in parts]
    else:
        chosen = next((cmd for cmd in ("code", "nano", "vim", "vi") if shutil.which(cmd)), None)
        if not chosen:
            raise ValueError(f"Set AUDIOBOOK_EDITOR, e.g. 'code --wait --goto {{file}}:{{line}}'. File: {path}:{line}")
        parts = [chosen]
    name = Path(parts[0]).stem.lower()
    if name in {"code", "code-insiders"}:
        return [*parts, "--wait", "--goto", f"{path}:{line}"]
    if name in {"nano", "vim", "vi", "nvim", "emacs"}:
        return [*parts, f"+{line}", str(path)]
    return [*parts, str(path)]


def play(path, at=0, duration=None):
    if not shutil.which("ffplay"):
        raise ValueError(f"Install ffplay for playback. Audio is available at {path}")
    command = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-ss", str(max(0, at))]
    if duration is not None:
        command += ["-t", str(duration)]
    subprocess.run([*command, str(path)], check=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    session_path = Path.cwd() / ".editorial-session.json"
    session = read_json(session_path, {})
    if argv and argv[0] in COMMANDS:
        book, command, rest = session.get("project"), argv[0], argv[1:]
    else:
        if len(argv) < 2:
            raise ValueError("Use python run.py BOOK edit")
        book, command, rest = argv[0], argv[1], argv[2:]
    parser = argparse.ArgumentParser(prog=f"python run.py [BOOK] {command}",
        description="Edit manuscript.txt; locate by p35, a phrase, passage ID, or 01:03:23. BOOK is remembered.")
    parser.add_argument("query", nargs="*", help="Page, phrase, timestamp, passage/issue ID (or two IDs for join)")
    parser.add_argument("-v", "--version", help="Reviewed version, e.g. v1; legacy for pre-import timestamps")
    parser.add_argument("--note", default="", help="Feedback, decision, or dismissal explanation")
    parser.add_argument("--by", dest="actor", default="", help="Checker/reviewer name (required for review actions)")
    parser.add_argument("--provider")
    parser.add_argument("--voice")
    parser.add_argument("--speed", type=float)
    parser.add_argument("--eq", choices=["smooth", "balanced", "flat"])
    parser.add_argument("--approvals", type=int)
    parser.add_argument("--title", help="Delivery title")
    parser.add_argument("--artist", help="Delivery author/artist")
    parser.add_argument("--page-offset", type=int, default=0, help="PDF page minus printed page, for initial import")
    parser.add_argument("--accept-speech", action="store_true", help="Confirm existing speech overrides after changing their source")
    parser.add_argument("--no-open", action="store_true", help="Print file and line without opening an editor/player")
    parser.add_argument("--no-context", action="store_true", help="Preview selected passage without adjacent passages")
    parser.add_argument("--before", help="Split the selected passage before this unique phrase")
    parser.add_argument("--output", help="New filename for approved delivery export")
    parser.add_argument("--input", help="Source PDF for import/reocr")
    parser.add_argument("--page", type=int, help="Single PDF page for a new OCR comparison")
    args = parser.parse_args(rest)
    if not book:
        parser.error("Choose a book once: python run.py BOOK edit")
    from src.pipeline_v3 import ProjectManager, infer_book_and_project, normalize_cli_path
    name, project = infer_book_and_project(book)
    if not Path(project).exists() and command != "import":
        parser.error("Project does not exist")
    ws = Workspace(project)
    query = " ".join(args.query)
    open_request = None
    try:
        with ws.lock():
            config = read_json(ws.home / "settings.json", {})
            legacy = read_json(ws.root / "05_audio_chunks" / "manifest.json", {})
            provider = args.provider or config.get("provider") or legacy.get("provider")
            prior_provider = config.get("provider") or legacy.get("provider")
            if args.provider and prior_provider and args.provider != prior_provider and not args.voice:
                raise ValueError("When changing providers, specify its voice too: settings --provider PROVIDER --voice VOICE")
            voice = args.voice or config.get("voice") or (legacy.get("voice") if not args.provider else None)
            manager = ProjectManager(str(ws.root), tts_provider=provider, tts_voice=voice, book_name=name)
            if command in {"import", "reocr"}:
                pdf = args.input or (book if str(book).lower().endswith(".pdf") else ws.root / "00_scanned.pdf")
                if command == "import" and args.page:
                    raise ValueError("Initial import processes the whole PDF. Use reocr --page for a comparison.")
                print(ws.intake(normalize_cli_path(str(pdf)), manager, reocr=command == "reocr", pages=[args.page] if args.page else None, page_offset=args.page_offset))
                write_json(session_path, {"project": str(ws.root)})
                return 0
            ws.initialize(manager, args.page_offset)
            if command == "reconcile-pages":
                changed = ws.reconcile_pages(args.page_offset)
                print(f"Reconciled printed page labels; updated {changed} passages.")
                return 0
            if args.provider or args.voice or command == "settings":
                ws.settings(provider=manager.tts_provider, voice=manager.tts.voice,
                            speed=args.speed, eq=args.eq, required_approvals=args.approvals, title=args.title, artist=args.artist)
            elif any(x is not None for x in (args.speed, args.eq, args.approvals, args.title, args.artist)):
                ws.settings(speed=args.speed, eq=args.eq, required_approvals=args.approvals, title=args.title, artist=args.artist)
            write_json(session_path, {"project": str(ws.root), "passage": session.get("passage") if session.get("project") == str(ws.root) else None})
            remembered = read_json(session_path, {}).get("passage")

            if command in {"edit", "find", "play", "preview", "pdf", "take"}:
                query = query or remembered or ""
                matches = ws.locate(query, args.version)
                if not matches:
                    raise ValueError("No match. Try a page (p35), shorter phrase, or the original review version.")
                if command == "find":
                    for match in matches:
                        t = match.get("timing")
                        span = f" {t['start_seconds']:.1f}–{t['end_seconds']:.1f}s" if t else ""
                        print(f"{match['id']}  p{match['page']} / PDF {match['pdf_page']}  line {match['line']}{span}  match={match['score']:.2f}\n  {match['text'][:240]}")
                    return 0
                # Page navigation may open the first paragraph; phrase ambiguity never auto-edits.
                if command == "edit" and (not query or page_label(query) is not None):
                    selected = matches[0]
                else:
                    selected = ws.choose(query, args.version)
                pid = selected["id"]
                write_json(session_path, {"project": str(ws.root), "passage": pid})
                if command == "edit":
                    # Never modify submitted snapshots. Resolve descendants in current manuscript.
                    current = parse(ws.manuscript.read_text(encoding="utf-8"))
                    targets = [p for p in current if p.id == pid or pid in p.parents.split()]
                    if len(targets) != 1:
                        raise ValueError("Old passage was removed/split. Current descendants: " + ", ".join(p.id for p in targets))
                    target = targets[0]
                    if args.version:
                        print(f"Feedback location is from {args.version}; opening current draft {target.id}.")
                    line = target.line
                    # Jump to the word itself, when present, not just the passage header.
                    lines = ws.manuscript.read_text(encoding="utf-8").splitlines()
                    if query and query not in {pid, f"p{target.page}"}:
                        start = line - 1
                        end = next((n for n in range(start+1, len(lines)) if lines[n].startswith("=== Passage ")), len(lines))
                        line = next((n+1 for n in range(start, end) if query in lines[n]), line)
                    print(f"{ws.manuscript}:{line}")
                    if not args.no_open:
                        open_request = editor_command(ws.manuscript, line)
                elif command == "preview":
                    if args.version:
                        raise ValueError("Preview uses current draft. Use play with --version for submitted audio.")
                    path = ws.preview(manager, pid, context=not args.no_context)
                    print(path)
                    if not args.no_open:
                        play(path)
                elif command == "take":
                    if args.version:
                        raise ValueError("New takes apply to the current draft only")
                    passages = ws.save()
                    next(p for p in passages if p.id == pid).take += 1
                    ws.save(render(passages))
                    print(f"New take requested for {pid}. Run preview or build.")
                elif command == "pdf":
                    pdf = next(iter((ws.root / "00_ocr").glob("*.pdf")), ws.root / "00_scanned.pdf")
                    if not pdf.exists():
                        raise ValueError("Source PDF is missing")
                    print(f"{pdf} — PDF page {selected['pdf_page']}")
                    if not args.no_open:
                        import webbrowser
                        webbrowser.open(pdf.as_uri() + f"#page={selected['pdf_page']}")
                else:
                    if args.version == "legacy":
                        raise ValueError("Legacy timings can locate text, but the old audio is not snapshotted. Submit a build for versioned playback.")
                    rec = ws.build_record(ws.version(args.version)["build"] if args.version else None)
                    timing = next((o for o in rec["offsets"] if o["chunk_id"] == pid), None)
                    if not timing:
                        raise ValueError("No audio for this draft passage; preview or build first")
                    start = seconds(query) if re.fullmatch(r"\d+:\d{2}(?::\d{2})?(?:\.\d+)?", query) else timing["start_seconds"]
                    path = ws.home / "builds" / rec["id"] / "audiobook.mp3"
                    print(f"{path} @ {start:.2f}s (saved build; use preview for unsaved audio changes)")
                    if not args.no_open:
                        play(path, max(0, start-2), timing["end_seconds"] - max(0, start-2) + 2)
            elif command == "validate":
                ws.save(accept_speech=args.accept_speech)
                ws._compiled(manager)
                print("Manuscript and speech instructions are valid for this provider. Voice/language support is checked by TTS during preview.")
            elif command == "build":
                rec = ws.build(manager)
                print(f"Build complete: {rec['total']} passages; {rec['reused']} cached.\n{ws.home / 'builds' / rec['id'] / 'audiobook.mp3'}\nRun submit when ready for checking.")
            elif command == "submit":
                version = ws.submit(manager)
                print(f"Submitted {version['id']}. Share this entire folder for offline checking:\n{ws.home / 'reviews' / version['id']}\nOpen index.html; checkers can download feedback for import.")
            elif command == "feedback":
                if args.input:
                    print(f"Imported {ws.import_feedback(args.input)} new feedback events.")
                else:
                    print(json.dumps(ws.issue(args.version, query or remembered or "", args.note, args.actor), ensure_ascii=False, indent=2))
            elif command == "issues":
                for issue in ws.issues(args.version):
                    times = ", ".join(f"{o['start_seconds']:.1f}s" for o in issue['current_times'])
                    print(f"{issue['id']} [{issue['status']}] reported {issue['version']} / {issue['passage']}\n  {issue['body']}\n  current: {', '.join(issue['current_passages']) or 'removed'} {times}")
            elif command in {"verify", "reopen", "dismiss"}:
                ws.resolve(query, args.version, {"verify": "verified", "reopen": "reopened", "dismiss": "dismissed"}[command], args.actor, args.note)
                print("Review event saved.")
            elif command in {"approve", "request-changes"}:
                ws.decide(args.version, args.actor, "approved" if command == "approve" else "changes_requested", args.note)
                print("Decision saved for the submitted version.")
            elif command == "deliver":
                if not args.output:
                    raise ValueError("Choose a new output filename with --output")
                print(ws.export(args.output, args.version))
            elif command == "undo":
                ws.undo()
                print("Restored prior manuscript; previous draft retained in .editorial/history.")
            elif command == "split":
                if not args.before:
                    raise ValueError("Provide the unique split phrase with --before")
                ws.split(query or remembered, args.before)
                print("Passage split; parent links retained.")
            elif command == "join":
                if len(args.query) != 2:
                    raise ValueError("Provide two adjacent passage IDs")
                ws.join(*args.query)
                print("Passages joined; parent links retained. Check page references and delivery settings.")
            elif command == "page-map":
                if len(args.query) != 2:
                    raise ValueError("Use page-map PDF_PAGE PRINTED_LABEL (e.g. page-map 37 35)")
                passages = ws.save()
                affected = [p for p in passages if p.pdf_page == args.query[0]]
                if not affected:
                    raise ValueError("No passages on that PDF page")
                save_printed_page_override(ws.root, args.query[0], args.query[1])
                for p in affected:
                    p.page = args.query[1]
                ws.save(render(passages))
                print(f"Updated page label for {len(affected)} passages and persisted the PDF-page map.")
            elif command == "settings":
                print(json.dumps(ws.settings(), indent=2))
            elif command == "history":
                print(json.dumps(read_json(ws.home / "review.json", {"versions": [], "issues": []})["versions"], indent=2))
        # Do not hold the project operation lock while a human edits. Preview
        # and build can run in another terminal against the latest saved file.
        if open_request:
            subprocess.run(open_request, check=True)
            with ws.lock():
                ws.save(accept_speech=args.accept_speech)
            print("Saved. Use preview to listen; build to assemble all changes.")
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
