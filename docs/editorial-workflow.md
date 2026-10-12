# Manuscript editing and versioned review

This is an opt-in CLI workflow over the existing OCR, TTS and mastering code.
Each migrated book has one authoritative `manuscript.txt`. Generated stage JSON
is no longer an editing surface. Existing book files are retained.

## Start

From the repository root, in the same environment used for the existing CLI:

```sh
# Existing project: import its accepted segments and pronunciation edits once.
python run.py BOOK edit --no-open

# New PDF, including scans/mixed documents: explicit extraction/OCR then manuscript.
python run.py /path/to/book.pdf import

# Configure an editor once. Any command with {file} and {line} placeholders works.
export AUDIOBOOK_EDITOR='code --wait --goto {file}:{line}'
python run.py edit p35
```

`BOOK` is remembered in `.editorial-session.json` in the current directory.
Subsequent commands can omit it. No project data is migrated until `edit` or
another editorial command is explicitly run for that book. Initial import
refuses conflicting source text in the existing segment/phonetics files.

The existing pronunciation layer is preserved when it differs from the current
dictionary output. Default speech inherits from the transcript and configured
pronunciation dictionary. Rules that were never applied to existing artifacts
are not silently applied during migration; inspect the imported manuscript.

`import` uses sufficiently substantial, non-corrupt embedded text per page and
falls back to the existing OCR service. Scans need `GEMINI_API_KEY`. Extraction
checkpoints are source-bound and resumable. Reading order and OCR quality still
require human review. Existing stage `0` remains available before migration.

## Navigate without finding files

```sh
python run.py find p35
python run.py edit "मुगल"
python run.py find "mughal saltanat"
python run.py edit 01:03:23 -v v1
python run.py edit i3
python run.py pdf
python run.py play
```

Exact phrase matches take priority. Approximate/Romanized matches are suggestions:
use the printed passage ID to select one. Repeated phrases also require an ID.
Page navigation opens the first passage on that page. `find` prints all matches.
The selected passage is remembered, so `play`, `preview`, and `edit` can omit it.

`-v v1` interprets a timestamp against the recording that was checked. Editing
then opens the corresponding **current draft**, never the submitted snapshot.
If that passage was split, choose a descendant from the listed IDs.
Pre-migration `offsets.json` can be searched with `-v legacy`; old audio is not
implicitly claimed to be a reviewed snapshot. Exact word-level audio alignment
is not implemented; playback seeks the supplied time or the passage boundary.

`pdf` opens the source PDF at its scan-page number in the default browser/PDF
viewer (viewer support for the page fragment varies). `--no-open` prints paths
and locations without launching an editor/player. Audio playback requires
`ffplay`; generation/mastering requires `ffmpeg` and `ffprobe`.

## Edit the manuscript

```text
=== Passage chunk_0142 ===
PAGE: 35
PDF_PAGE: 37
TYPE: prose
PAUSE_AFTER_MS: 600
RATE: +0%
PITCH: +0Hz
VOLUME: +0%
TAKE: 0
PARENTS:

TEXT:
मुगल सल्तनत का विस्तार ...

SPEECH:
(inherit)
```

* Correct OCR in `TEXT`.
* Put an alternate spoken rendition of the **whole passage** under `SPEECH`.
  `(inherit)` means use the corrected transcript and current dictionary rules.
* Replace the `SPEECH:` section with `SSML:` for authored markup. Fragments are
  wrapped in `<speak>`. Do not keep both sections.
* Change boundary silence in `PAUSE_AFTER_MS`; this does not call TTS again.
* Change `RATE`, `PITCH`, or `VOLUME` only where the chosen adapter implements it.
* Increment `TAKE` (or run `take`) to request fresh speech with identical text.
* Edit `PAGE` for the printed label; `PDF_PAGE` always refers to the scan position.
  Labels can be roman numerals or other text. `?` means not mapped yet.

Keep passage IDs and section labels. They are navigation/feedback anchors.
Use `split`/`join` to retain lineage. Reorder whole passage blocks to change
reading order, or remove a block to omit narration. Removed passages are listed
in the next submission. New passages need unique alphanumeric/underscore IDs.
Reserved section/header lines must not be used as standalone manuscript content.

If `TEXT` changes while its explicit speech override remains identical, validation
stops. Update/remove the override or, after checking it, explicitly run
`validate --accept-speech`. The manuscript remains editable even with unresolved
OCR markers, but those passages cannot be synthesized.

```sh
python run.py page-map 37 35
python run.py split chunk_0142 --before "अगला वाक्य"
python run.py join PASSAGE_ONE PASSAGE_TWO
python run.py validate
python run.py undo
```

`--page-offset 2` on the **first** import/edit maps PDF 37 to printed 35.
Irregular numbering can then be corrected in the manuscript or with `page-map`.
Join inherits the first passage's page/delivery settings and the last passage's
boundary pause; review those fields, especially across pages. Explicit speech
overrides must be redistributed/removed before splitting/joining.

Every validated save creates a content-addressed history snapshot. `undo` restores
the previous validated revision; an unvalidated current file is backed up first.
External-editor saves are validated when the editor returns or the next editorial
operation runs. History is in `.editorial/history/`; no file watcher is required.

## Preview, build, and submit

```sh
python run.py preview --no-open
python run.py build
python run.py submit
```

Preview includes adjacent passages and uses the same voice, mastering speed and
EQ as the final build. `--no-context` previews just the selected passage, useful
while neighboring OCR remains unresolved. Successful previews are cached for
the next build. Save several edits before building if preferred.

Build reads a validated manuscript snapshot, reuses unchanged speech, assembles
audio and recalculates timing. Boundary-only changes require no new TTS. A failed
build retains the previous successful build and completed cache entries. A text
editor can remain open while a build runs; later saves belong to a later build.

`submit` requires a successful build matching the current draft and settings.
It creates `v1`, `v2`, etc., plus `.editorial/reviews/vN/`. Share that **entire
folder** with a checker; open `index.html`. The pack includes audio, transcript,
source PDF when available, changed-passage filters, and previous audio for A/B
comparison. No web server or checker installation is needed. Treat these packs
as private book content and retain them for as long as the review is needed.

```sh
python run.py settings --provider google --voice hi-IN-Neural2-B
python run.py settings --speed 1.10 --eq smooth --title "मन साधे जीवन सधै"
```

Final speed is always applied from source WAVs, not repeatedly to the last MP3.
Player playback speed is only a listening aid. Provider/model identity, effective
speech, delivery and explicit take determine audio caching. Provider-side model
changes cannot be inferred; increment TAKE when a fresh rendition is needed.

## Feedback and further rounds

Checkers use the offline pack to play passages, open scans, report problems,
verify corrections and download feedback. Notes are locally retained where the
browser supports storage; downloading is the reliable handoff.

```sh
python run.py feedback --input downloaded-feedback.json
python run.py issues
python run.py edit i1
python run.py preview
python run.py build
python run.py submit
```

Repeated import of the same downloaded note is idempotent. Import validates the
book build/version and all notes before committing the batch. Older-version
feedback remains accepted and points to its original audio. New submissions
map it to current passages/times; split/join lineage is retained. Verification
is carried forward only when the relevant text, audio and settings still match.

For existing checker notes, find the passage then record the note directly:

```sh
python run.py feedback chunk_0142 -v v1 --by checker1 --note "मुगल sounds like मुसल"
python run.py verify i1 -v v2 --by checker1
python run.py reopen i1 -v v2 --by checker1
python run.py dismiss i1 -v v2 --by checker1 --note "Verified against the scan; report was incorrect"
```

Automatic parsing of arbitrary WhatsApp/free-text batches is not included.
Feedback can be anchored to an existing paragraph near an omitted word; insert
the missing text there. An issue whose passage was removed stays visible for
checking/dismissal. Reports are never silently treated as fixes.

## Final review and delivery

```sh
python run.py approve -v v2 --by checker1
python run.py approve -v v2 --by checker2
python run.py deliver -v v2 --output /path/to/approved-book-v2.mp3
```

Approvals are per version; the default is two distinct named reviewers. Set a
different count with `settings --approvals N` before building/submitting.
`request-changes --by checker1` withdraws that reviewer's approval. Any current
request for changes or unresolved issue blocks delivery. Reopen also blocks
delivery. Export refuses to overwrite an existing destination.

Reviewer names in this **local CLI/offline workflow are attribution, not verified
authentication**. Final reviewers should still listen to the assembled book for
joins, order, completeness, loudness and pace. Changed-passage checking alone
does not establish complete audiobook quality.

## OCR retries and compatibility

```sh
python run.py reocr --page 37
```

This writes a separate OCR suggestion and comparison under `.editorial/intake/`.
It never overwrites `manuscript.txt`. Manually accept relevant changes against
the scan. OCR reruns use their own resumable checkpoints; delete no book files.

For migrated books, legacy CLI stage commands refuse to use stale intermediate
files; `all` delegates to the new build command. The existing stage-based web
application is **not the editor for migrated books**: its mutation endpoints and
queued legacy jobs reject these projects to prevent two divergent drafts. Use
the CLI and offline review packs. Unmigrated books retain their existing behavior.
Old web review records are retained but are not converted into CLI review events;
start a new submitted version and attach outstanding feedback to it explicitly.

SSML transport is enabled for the Google Cloud and Azure adapters. The editor
accepts a conservative tag/attribute subset and rejects markup for adapters that
strip it. Particular voice/language support is still checked by the provider
during preview; valid XML alone does not guarantee a phoneme is supported.
References: [Google SSML](https://docs.cloud.google.com/text-to-speech/docs/ssml),
[Azure SSML structure](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-structure).
