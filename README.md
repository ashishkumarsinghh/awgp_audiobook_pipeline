# AWGP Audiobook Pipeline

## New manuscript editing workflow (CLI)

```sh
python run.py BOOK edit --no-open   # Import existing accepted text once
python run.py edit p35             # Open manuscript.txt at the printed page
python run.py find "मुगल"           # Search transcript and speech overrides
python run.py preview              # Listen to the selected passage and context
python run.py build                # Reuse unchanged speech and rebuild audio
python run.py submit               # Create a fixed version and offline checker pack
```

The book and selected passage are remembered. Set `AUDIOBOOK_EDITOR` to your
preferred editor. New PDFs can start with `python run.py /path/book.pdf import`.
Once migrated, edit `manuscript.txt`; stage JSON is no longer authoritative.
Checkers open the submitted folder's `index.html` and download feedback for
`python run.py feedback --input feedback.json`.

See [the complete editing, review, and delivery guide](docs/editorial-workflow.md)
for SSML, version-specific timestamps, undo, approvals, migration boundaries,
and the legacy web UI restriction for migrated books. The stage instructions
below continue to apply to **unmigrated** projects.

Convert scanned Hindi/Sanskrit books into reviewed, resumable audiobooks.

The pipeline keeps two separate representations:

- \`source_text\`: the OCR transcript. It must remain faithful to the page.
- \`pronunciation_text\`: an editable TTS-only pronunciation layer. Respelling a word here never changes the transcript.

OCR excludes repeated headers, footers, page numbers, watermarks, URLs, publisher overlays, and advertisements. Unreadable text is marked \`[???????]\` instead of being guessed.

## 1. Install once

Run from the repository root:

~~~sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
ffmpeg -version
~~~

Optional web application:

~~~sh
cd frontend
npm ci
cd ..
uvicorn api:app --host 127.0.0.1 --port 8000
~~~

For OCR of scanned pages, set \`GEMINI_API_KEY\`. For TTS choose one provider:

~~~sh
export GEMINI_API_KEY="..."
export TTS_PROVIDER=edge
export TTS_VOICE=hi-IN-SwaraNeural
export PRONUNCIATION_FILE=configs/improved_pronunciation.json
~~~

Provider examples:

- \`edge\`: \`hi-IN-SwaraNeural\` or \`hi-IN-MadhurNeural\`
- \`sarvam\`: requires \`SARVAM_API_KEY\`
- \`google\`: requires Google Cloud ADC
- \`azure\`: requires \`AZURE_SPEECH_KEY\` and \`AZURE_SPEECH_REGION\`
- \`studio\`: requires \`GEMINI_API_KEY\`

Google Cloud supports Hindi voices and SSML phoneme/custom-pronunciation controls. See [Hindi voices](https://cloud.google.com/text-to-speech/docs/voices) and [SSML phonemes](https://cloud.google.com/text-to-speech/docs/phonemes).

## 2. Convert a complete PDF

Use a stable project name. A Windows PDF path is easiest through its WSL path:

~~~sh
. venv/bin/activate
export GEMINI_API_KEY="..."
export TTS_PROVIDER=edge
export TTS_VOICE=hi-IN-SwaraNeural

python run.py "/mnt/c/Users/ashis/Downloads/HINR0862_NAE_JIVAN_KI_NAYI_PRERANA_1st1964.pdf" all
~~~

The PDF path creates a project under:

~~~text
projects/HINR0862_NAE_JIVAN_KI_NAYI_PRERANA_1st1964/
~~~

To test only selected pages first:

~~~sh
python run.py "/mnt/c/Users/ashis/Downloads/HINR0862_NAE_JIVAN_KI_NAYI_PRERANA_1st1964.pdf" 0 --page 1
python run.py "/mnt/c/Users/ashis/Downloads/HINR0862_NAE_JIVAN_KI_NAYI_PRERANA_1st1964.pdf" 0 --max-pages 10
~~~

\`all\` runs OCR, segmentation, pronunciation/prosody, audio, and mastering/export. OCR checkpoints make interrupted runs resumable. Audio manifests regenerate only missing or changed chunks.

## 3. Stage map

Run \`python run.py <book-or-project> <stage>\`:

| Stage | Command name | Reads | Writes |
|---|---|---|---|
| 0 | \`ocr\` | PDF | \`00_ocr/ocr_raw.txt\`, \`00_ocr/text_cleaned.txt\`, page checkpoints |
| 1 | \`segment\` | cleaned OCR | \`01_segments/segments.json\` |
| 2 | \`phonetics\` | segments | \`02_phonetics/phonetics.json\` |
| 3 | \`audio\` | phonetics | \`03_audio/*.wav\`, \`manifest.json\` |
| 4 | \`master\` | audio + phonetics | \`04_master/mastered.mp3\` |
| 5 | \`speed\` | mastered MP3 | tempo-adjusted delivery MP3 |
| 6 | \`metadata\` | mastered MP3 | tagged final MP3 |

Numeric aliases are also accepted: \`0\` through \`6\`.

For a named project:

~~~sh
python run.py HINR0862_NAE_JIVAN_KI_NAYI_PRERANA_1st1964 0
python run.py HINR0862_NAE_JIVAN_KI_NAYI_PRERANA_1st1964
~~~

## 4. Review and edit safely

Run one stage at a time when human review is required. A later stage never silently reruns an earlier stage.

### OCR review

Open and correct:

~~~text
projects/<book>/00_ocr/text_cleaned.txt
~~~

Then regenerate segments:

~~~sh
python run.py <book> 1 --force
~~~

Never correct OCR by editing phonetics. Correct the transcript first. Preserve the printed spelling. If the page is genuinely unclear, use \`[???????]\`; generation will stop until it is resolved.

### Segmentation review

Edit:

~~~text
projects/<book>/01_segments/segments.json
~~~

You may adjust chunk boundaries and \`segment_type\`. Keep \`source_text\` verbatim. Then run:

~~~sh
python run.py <book> 2 --force
~~~

### Pronunciation/prosody review

Edit:

~~~text
projects/<book>/02_phonetics/phonetics.json
~~~

Use \`pronunciation_text\` for TTS-only fixes such as:

~~~json
{
  "source_text": "???? ?? ????-?????",
  "pronunciation_text": "??? ?? ???? ?????"
}
~~~

Do not replace \`source_text\`. Adjust \`rate\`, \`pitch\`, \`volume\`, and pauses only when needed. Then synthesize:

~~~sh
python run.py <book> 3
~~~

Only changed or missing audio chunks are regenerated.

### Audio and mastering review

Listen to chunks in \`03_audio/\`. If the phonetics file is correct:

~~~sh
python run.py <book> 3
python run.py <book> 4 --speed 1.15
python run.py <book> 6
~~~

For a different final tempo:

~~~sh
python run.py <book> 5 --speed 1.10
python run.py <book> 6
~~~

## 5. Efficient editing loop

~~~sh
# Initial generation
python run.py <book> 0
python run.py <book> 1
python run.py <book> 2
python run.py <book> 3
python run.py <book> 4
python run.py <book> 6

# After OCR/source edits
python run.py <book> 1 --force
python run.py <book> 2 --force
python run.py <book> 3
python run.py <book> 4
python run.py <book> 6

# After segment edits
python run.py <book> 2 --force
python run.py <book> 3
python run.py <book> 4
python run.py <book> 6

# After pronunciation or prosody edits
python run.py <book> 3
python run.py <book> 4
python run.py <book> 6
~~~

Use the dashboard at any time:

~~~sh
python run.py <book>
~~~

Do not edit the same project simultaneously through the web UI and CLI.

## 6. Project artifacts

~~~text
projects/<book>/
  00_ocr/
    00_scanned.pdf
    ocr_raw.txt
    text_cleaned.txt
    checkpoints/
  01_segments/
    segments.json
  02_phonetics/
    phonetics.json
  03_audio/
    chunk_0001.wav
    manifest.json
  04_master/
    mastered.mp3
    <book>.mp3
  artifacts/
~~~

\`artifacts/\` contains timestamped history. Do not delete checkpoints or manifests while a stage is running.

## 7. Validation

~~~sh
venv/bin/python -m pytest -q
venv/bin/python -m compileall -q src api.py
venv/bin/python -m pip check
~~~

Before publishing, review:

- no \`[???????]\` markers remain;
- no page numbers, headers, footers, URLs, or publisher text are present;
- OCR wording matches the scan;
- pronunciation edits exist only in \`pronunciation_text\`;
- hyphenated Hindi compounds sound natural;
- chunk transitions contain no duplicate or abrupt pauses;
- the final MP3 has been listened to end-to-end.

## 8. Editor and Checker web workflow

## 8.5 Automated audiobook QA

Run the fast deterministic gate after audio/mastering, or let `all` run it
automatically:

~~~sh
venv/bin/python scripts/run_audio_qa.py projects/<book>
~~~

It checks stage counts and order, source-text drift, provenance, unresolved
OCR, pronunciation contracts, chunk integrity, clipping, silence, pace, the
final MP3, and final-master playback offsets. Results are written to
`07_qa/report.json`; `FAIL` blocks delivery and `REVIEW` requires a checker.

For a quick checker-like listening proxy, use a reproducible risk sample. It
prints progress and ETA, caches by audio hash plus recognizer settings, and
never treats low-confidence or romanized ASR as proof of correct pronunciation:

~~~sh
venv/bin/python scripts/run_checker_simulation.py projects/<book> \
  --model tiny --sample-percent 10 --max-chunks 24
~~~

Use `--all` only for a deliberate release audit. The optional backend is
`faster-whisper`; its Hindi output is useful for omissions, insertions, and
word-level disagreement, but Sanskrit and pronunciation quality still require
human listening. Missing dependencies produce `NOT_EVALUATED`, not `PASS`.
Pronunciation aliases are scoped to the production configuration and project;
source text is retained separately and reviewer suggestions such as editorial
deletions require explicit approval.

The API and React dashboard are intended for editors and Checkers who should not
need to edit JSON files manually.

Start the API from the repository root:

~~~sh
. venv/bin/activate
uvicorn api:app --host 127.0.0.1 --port 8000
~~~

In a second terminal, start the dashboard:

~~~sh
cd frontend
npm ci
npm run dev
~~~

Open the URL printed by Vite (normally `http://localhost:5173`). The Vite
development proxy forwards `/api` requests to the API on port 8000. For a
different API host, set `VITE_API_BASE` before starting Vite.

Projects migrated to the manuscript workflow are intentionally read-only in the
legacy dashboard. Use the `run.py` edit/build/submit commands and the generated
review pack documented above for editing and delivery.

The dashboard now detects migrated projects and switches to the same manuscript
service used by the CLI. It reads and saves `manuscript.txt`, validates the
authoritative draft, and invokes the shared build/submit/undo operations through
`/api/projects/<book>/manuscript/...`; it does not create a second stage draft.

Typical roles are:

1. An Editor creates or selects a project, starts the PDF pipeline, and corrects
   OCR, segmentation, pronunciation, or prosody.
2. The Editor runs the required downstream stages and creates a mastered review
   candidate.
3. A Checker listens while comparing the candidate with the textbook and records
   each issue with page, segment, time range, severity, and notes.
4. The Editor applies corrections and regenerates only the affected stages.
5. The next mastered output becomes a new candidate. The previous candidate is
   retained for audit, and unresolved issues are copied to the new candidate with
   a parent link so they cannot disappear between review rounds.
6. A Checker verifies the new candidate. `fixed_pending_check` issues remain
   approval blockers until explicitly verified, resolved, or dismissed. Two
   independent approvals are required before publication.

Always select the candidate being reviewed when submitting an issue or decision.
Historical candidate audio remains available for comparison, but decisions belong
to the current candidate only.

If another person edited the draft since a correction note was written, the API
rejects the correction with a conflict. Reload the project, confirm the target
text, preview the correction again, and then apply it.

For the complete data model, API behavior, migration notes, and recovery rules,
see [the feedback workflow implementation guide](docs/feedback-workflow-implementation-guide.md).

## 9. Troubleshooting quick reference

- **No audio is regenerated:** confirm the canonical file under `02_phonetics/`
  changed, then run Stage 3 with `--force` only if the manifest is stale.
- **A correction returns 409:** another draft revision exists; reload before
  applying the correction.
- **A Checker cannot approve:** inspect unresolved blocker issues, including
  `fixed_pending_check`, on the current candidate.
- **A run stops after interruption:** rerun the same stage. Checkpoints and the
  audio manifest are designed to resume safely.
- **OCR is uncertain:** resolve every `[???????]` marker before synthesis.
- **The UI cannot reach the API:** confirm `uvicorn` is listening on port 8000,
  or set `VITE_API_BASE` to the reachable API URL.
# Sentence-level feedback review

Romanized checker notes and historical timestamps are not reliable enough to select
review clips: timestamps can move between masters, and a note such as `gali gali`
may refer to only part of a long segment. Build the sentence-level review pack to
match each note against the Hindi source and show the exact source and spoken text:

```bash
venv/bin/python scripts/build_sentence_review_pack.py \
  projects/HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014_google_tts
```

Open the generated `07_qa/sentence_review_pack/index.html`. Candidate matches are
kept separate from `needs_human_selection`; unresolved notes are never silently
attached to a nearby sentence. Optional isolated diagnostic clips can be generated
with `--synthesize`, but that invokes Google TTS and should only be used when the
extra provider usage is authorized.
