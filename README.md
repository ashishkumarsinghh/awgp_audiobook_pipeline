# AWGP audiobook pipeline

A local FastAPI + React workflow for transcribing Hindi/Sanskrit PDF books, reviewing text and pronunciation, generating narration, and mastering an MP3.

## Run locally

Run commands from the repository root. Stage execution is persisted in the
database and claimed by a lease-based worker in each API process. Multiple
workers can share the queue; SQLite remains best for local/small deployments,
while PostgreSQL is recommended for concurrent production workers.

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
| SARVAM_API_KEY | Sarvam AI Bulbul TTS API key (for authentic Indian language voices). |
| TTS_PROVIDER | edge by default; sarvam (Sarvam AI Bulbul v3); studio (Google AI Studio); google (Google Cloud Neural2/WaveNet). |
| TTS_VOICE | Optional provider voice; defaults to shubh for sarvam, Kore for studio, Swara for edge/azure, hi-IN-Neural2-B for google. |
| AZURE_SPEECH_KEY | Azure Speech subscription key (required only for Azure projects). |
| AZURE_SPEECH_REGION | Azure Speech region, for example `centralindia` (required only for Azure projects). |
| JWT_SECRET_KEY | Set a private random signing secret before sharing access to the API. |
| DATABASE_URL | Defaults to sqlite:///./audiobook_pipeline.db; tests use isolated in-memory databases. |
| JOB_WORKER_ENABLED | Enables the durable polling worker in each API process; defaults to `1`. |

Sarvam AI TTS (`--provider sarvam`) uses `SARVAM_API_KEY` and the `bulbul:v3` model to generate highly authentic, natural native Indian language speech (voices: `shubh`, `ashutosh`, `advait`, `ritu`, `priya`, `roopa`). Google AI Studio TTS (`--provider studio`) uses `GEMINI_API_KEY` to generate 24 kHz audio via `gemini-3.1-flash-tts-preview` (`Kore`, `Charon`). Google Cloud TTS (`--provider google`) uses Application Default Credentials (`gcloud auth application-default login`) with high-fidelity Neural2 voices (`hi-IN-Neural2-B`, `hi-IN-Neural2-A`). Edge requires network access. Azure requires the Azure Speech SDK and `AZURE_SPEECH_KEY`/`AZURE_SPEECH_REGION`. The editor exposes a curated catalog of high-quality Hindi voices across providers. Failures are explicit and providers are never silently substituted.

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

Stage requests create durable jobs. Workers claim one job per project using a
database lease, renew the lease while running, and reclaim expired jobs after a
worker crash. Repeating a failed stage queues it again and resumes from that
stage using the existing validated artifacts and audio manifest. The API
exposes `job_id` in stage responses, includes the latest job in project details,
and provides `GET /api/projects/{project_name}/jobs/{job_id}` for polling.

You may run any individual stage (`1` OCR, `2` segmentation, `3` phonetics,
`4` audio, or `5` mastering) or `all`; no earlier stage is implicitly rerun.
Review or repair the relevant artifact, then submit that stage again. Do not
edit the same project through the CLI while an API job is active.

## Minimal-verbosity CLI execution (`run.py`)

Run commands directly from the root folder without long arguments or flags:

~~~sh
python run.py <book_name> <stage>
~~~

### Quick stage mapping

| Stage | Command | Stage Subfolder | Input Picked | Output Saved | Human Edit Location |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **0** (OCR) | `python run.py my_book 0` | `00_ocr/` | `00_ocr/*.pdf` or `my_book.pdf` | `ocr_raw.txt` | `00_ocr/text_cleaned.txt` |
| **1** (Segmentation) | `python run.py my_book 1` | `01_segments/` | `00_ocr/text_cleaned.txt` / `ocr_raw.txt` | `segments.json` | `01_segments/segments.json` |
| **2** (Phonetics) | `python run.py my_book 2` | `02_phonetics/` | `01_segments/segments.json` | `phonetics.json` | `02_phonetics/phonetics.json` |
| **3** (Audio) | `python run.py my_book 3` | `03_audio/` | `02_phonetics/phonetics.json` | `chunks/*.wav` + `manifest.json` | Resumes pending/edited |
| **4** (Mastering) | `python run.py my_book 4` | `04_master/` | `02_phonetics/phonetics.json` + `03_audio/` | `mastered.mp3` | Master delivery audio |

### Workflow: Edit in subfolders & resume

Each stage automatically detects its input from the previous stage subfolder. All manual edits are made directly in the corresponding stage subfolder:

~~~sh
# 1. Run OCR (resumable per-page checkpoints in 00_ocr/checkpoints/):
python run.py brahma_sandhya 0

# 2. Review and edit text right in: projects/brahma_sandhya/00_ocr/text_cleaned.txt
# Then run Segmentation (automatically picks up your edits from 00_ocr/):
python run.py brahma_sandhya 1

# 3. Review and edit segment chunk boundaries right in: projects/brahma_sandhya/01_segments/segments.json
# Then run Phonetics (automatically picks up your edited segments):
python run.py brahma_sandhya 2

# 4. Review and edit pronunciation aliases & prosody in: projects/brahma_sandhya/02_phonetics/phonetics.json
# Then run Audio (automatically resumes and synthesizes only missing or changed chunks):
python run.py brahma_sandhya 3

# 5. Run Mastering to produce the final audiobook:
python run.py brahma_sandhya 4

# Check project status at any time:
python run.py brahma_sandhya

# Or run all stages sequentially:
python run.py brahma_sandhya all
~~~

### Artifact Naming & Resumability Structure

Every project folder organizes active state, stage subfolders, checkpoints, and immutable historical archives:

- **Stage Subfolders**: `00_ocr/`, `01_segments/`, `02_phonetics/`, `03_audio/`, `04_master/`.
- **OCR Page Checkpoints (`00_ocr/checkpoints/`)**: Saves individual page transcriptions (`<book>_page_0001.txt`, `ocr_manifest.json`). If OCR is interrupted, rerunning Stage 0 resumes from the pending page without reprocessing completed pages.
- **Historical Timestamped Artifacts (`artifacts/`)**: Every run archives a timestamped file with the book name:
  `<book_name>_<stage_label>_<tag>_<YYYYMMDD_HHMMSS>.<ext>`
  (e.g. `brahma_sandhya_00_ocr_raw_cli_20260917_195000.txt`, `brahma_sandhya_02_segments_cli_20260917_195100.json`).
- **Granular Audio Resume (`03_audio/manifest.json`)**: Tracks chunk fingerprints and SHA-256 digests. If phonetics are modified for only a few chunks, running Stage 3 re-synthesizes *only* the changed chunks.
- **Custom Flag Overrides**: Full compatibility flags (`--project`, `--stage`, `--input`, `--output`, `--voice`, `--provider`) remain available.

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
