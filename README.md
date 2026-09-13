# AWGP audiobook pipeline

A local FastAPI + React workflow for transcribing Hindi/Sanskrit PDF books, reviewing text and pronunciation, generating narration, and mastering an MP3.

## Run locally

Run commands from the repository root. Use one API worker; project locks are currently in-process.

~~~sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
# Install the system ffmpeg package and confirm:
ffmpeg -version
cd frontend
npm ci
cd ..
# For an existing database from an older checkout (stop the API first):
python scripts/migrate_db.py
uvicorn api:app --host 127.0.0.1 --port 8000
# In another terminal:
cd frontend
npm run dev
~~~

For a new installation, skip the migration until the API creates its database. The migration is idempotent and creates a timestamped SQLite backup before adding missing columns.

The frontend is at http://localhost:5173 and API documentation at http://localhost:8000/docs. The first registered account becomes administrator; later accounts are editors. Editors register their volunteer profile and request allocation; only administrators can assign books. Uploaded book titles are preserved for display, while the API generates a unique safe slug for storage and URLs.

Existing start.sh/start.ps1/start.bat launchers remain available. start.sh currently kills processes occupying its ports and exports .env through shell word splitting; use the explicit commands above when other services share the machine.

Set these variables in a local .env (do not commit credentials):

| Variable | Purpose |
| --- | --- |
| GEMINI_API_KEY | Remote scanned-page OCR. Without it, only embedded PDF text can be extracted. |
| OCR_MODEL | Overrides the existing default gemini-3.6-flash. Confirm model availability for your account. |
| TTS_PROVIDER | edge by default; gemini is the legacy name for the Google Cloud TTS adapter. |
| TTS_VOICE | Optional provider-compatible voice; project settings take precedence in the API. |
| AZURE_SPEECH_KEY | Azure Speech subscription key (required only for Azure projects). |
| AZURE_SPEECH_REGION | Azure Speech region, for example `centralindia` (required only for Azure projects). |
| JWT_SECRET_KEY | Set a private random signing secret before sharing access to the API. |
| DATABASE_URL | Defaults to sqlite:///./audiobook_pipeline.db; tests use isolated in-memory databases. |

Edge requires network access. Google Cloud TTS requires the optional google-cloud-texttospeech package and Application Default Credentials; `GEMINI_API_KEY` alone does not configure it. Azure requires the Azure Speech SDK and `AZURE_SPEECH_KEY`/`AZURE_SPEECH_REGION`. The editor exposes a curated catalog of high-quality Hindi voices for Edge, Google and Azure; Sanskrit uses the selected Hindi voice with the project pronunciation profile. Failures are explicit and providers are never silently substituted.

## Review and produce a book

1. Upload a PDF and run OCR.
2. Compare the transcription with the PDF and save reviewed text. Resolve every [अस्पष्ट] marker. Preserve intended punctuation, spelling and verse boundaries.
3. Run Segmentation and review source chunks.
4. Run Phonetics and review pronunciation aliases, rate, pitch and pauses.
5. Run Audio. Progress reports current completed chunks and individual errors. Retry after correcting an error to resume verified work.
6. Listen to the chunks, then run Mastering. Listen through the final book before publishing.
7. Final release requires two approvals from different human reviewers. A first approval moves the candidate to “Awaiting second approval”; unresolved blockers or a duplicate reviewer cannot complete release.

OCR preserves the existing transcription prompt. Shantikunj normalization helpers remain opt-in utilities, not an automatic rewrite of sacred text. Blank/unreadable pages stop OCR with their page number and require review rather than being silently skipped.

Source chunks have a hard 1,000-character limit and at most five sentence pieces. Long paragraphs and verses split at word boundaries. A single oversized OCR token produces a spacing-review error instead of splitting a Devanagari word. Paragraphs, semantic tags, punctuation runs and decimals are retained.

## Artifacts and retries

| Artifact | Meaning |
| --- | --- |
| 00_scanned.pdf | Uploaded source |
| 01_ocr_raw.txt | Raw transcription |
| 02_text_cleaned.txt | Human-reviewed text |
| 03_segments.json | Editable source segments |
| 04_phonetics.json | Editable pronunciation/prosody script |
| 05_audio_chunks/ | Mono 24 kHz 16-bit PCM WAVs |
| 05_audio_chunks/manifest.json | Input/voice fingerprints, audio digests, durations and errors |
| 06_mastered.mp3 | Mastered delivery audio |
| artifacts/ | Timestamped historical artifacts recorded by the API |

Saving changed source text invalidates downstream active artifacts. Identical saves preserve derived work. Source and phonetics edits are separate; source changes require rerunning Phonetics. Historical artifacts and reusable chunks remain. Changes to pronunciation, provider, voice, rate or pauses invalidate matching fingerprints.

Pre-manifest audio must be regenerated once. File size alone no longer establishes success. Retries reject corrupt/partial output and never fill missing narration with silence. Mastering requires every expected chunk in script order and publishes only after successful assembly. Both pause-before and pause-after values are honored. Polling uses fingerprints/file metadata; resume, chunk playback and mastering perform waveform/digest checks.

Do not run CLI stages concurrently with API edits or multiple API workers against one project. Background jobs are in-process; after restart, rerun Audio to resume from its manifest.

## CLI stage mapping

| Operation | CLI --stage | API /stage/ |
| --- | --- | --- |
| OCR | 0 | 1 |
| Segmentation | 1 | 2 |
| Phonetics | 2 | 3 |
| Audio | 3 | 4 |
| Mastering | 4 | 5 |

~~~sh
python -m src.pipeline_v3 --project projects/my_book --stage 1
python -m src.pipeline_v3 --project projects/my_book --all
~~~

Choose either --stage or --all. Place 00_scanned.pdf in the project directory before CLI OCR. For production, run stages individually and review text/pronunciation before synthesis.

## Validation

~~~sh
venv/bin/python -m pytest -q
venv/bin/python -m compileall -q src api.py
venv/bin/python -m pip check
cd frontend
npm test -- --run
npm run build
npm run lint
~~~

Pytest collects tests/ only. scripts/test_tts_providers.py is a manual network diagnostic, deliberately excluded from offline tests. Tests use isolated databases, temporary artifacts and provider doubles; live credentials are unnecessary.

See docs/architecture-review.md for findings and remaining work.
