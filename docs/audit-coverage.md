# Audit coverage matrix

This matrix records the targeted audit performed against the local FastAPI/React
pipeline. “Unverified” means the code or offline fixtures were insufficient to
make a claim.

| Scenario | Expected behavior / basis | Component | Validation and result | Status |
|---|---|---|---|---|
| Valid text-based synthetic PDF upload | Persist only after a readable, non-empty PDF is confirmed | `api.py`, PyMuPDF | Synthetic one-page upload passed | Verified |
| Empty upload | Reject before project creation | `api.py` | Returned 400; no project state | Verified |
| Malformed PDF labeled as PDF | Reject and remove staging directory | `api.py` | New test: returned 422; directory absent | Fixed |
| Encrypted/password-protected PDF | Clear unsupported response; no OCR/model call | `api.py`, `ocr_engine.py` | Structural validator rejects protected input; password-entry flow is unsupported | Verified / unsupported by design |
| Scanned page without OCR credentials | Do not silently produce text | OCR engine | Existing test identifies page and credential requirement | Verified |
| Empty OCR provider response | Identify page and fail rather than omit content | OCR retry loop | Existing mock test includes page number | Verified |
| OCR checkpoint reuse | Reuse non-empty page checkpoints | OCR checkpoint files | Code inspected; crash/restart fixture not run end-to-end | Unverified |
| Chunk schema, IDs, pauses, unresolved OCR markers | Reject invalid narration input | `src/core/artifacts.py` | Validation tests passed | Verified |
| Cache after text/voice/rate/pause/corruption changes | Regenerate stale or invalid chunks | synthesis runner | Manifest/digest tests passed | Verified |
| Provider failure, silence, partial WAV | Mark failed; never publish silence | synthesis runner | Audio safety tests passed | Verified |
| Missing chunk during dashboard polling | Do not report complete from manifest alone | `api.py` | Fast mode now checks existence and recorded size | Fixed |
| Ordered assembly and pause placement | Every validated chunk exactly once in script order | `AudioAssembler` | Synthetic WAV duration/order assertions passed | Verified structurally; listening unverified |
| Invalid/empty mastered MP3 download | Refuse publication | `api.py`, `audio/io.py` | New `validate_mp3` regression rejects invalid bytes | Fixed |
| Cross-project editor access | Deny unassigned editor | global project dependency | Authorization tests and canonical path checks passed | Verified |
| Artifact path traversal / prefix collision | Resolve within project root | API downloads/review | `commonpath` guards present | Verified structurally |
| Token forgery with unset secret | Never use a predictable signing key | API auth | Random fallback regression passed | Fixed; shared production secret still required |
| Long bcrypt password | Avoid silent 72-byte truncation | signup/login | 73-byte password regression passed | Fixed |
| Duplicate stage requests in one process | Serialize mutations | project lock | Lock logic inspected; stress test not run | Verified only for one process |
| Worker restart during background job | Durable recovery | DB jobs and leases | Lease heartbeat/reclaim logic plus job recovery test | Verified for DB-backed recovery; crash timing stress remains unverified |
| Cancellation | Stop work and preserve consistent state | API/pipeline | No cancellation endpoint found | Unsupported; UX should state this |
| Remote URL ingestion / SSRF | Not applicable | API | No URL ingestion endpoint found | N/A |
| Paid/live provider behavior | No live calls in audit | TTS adapters | Provider doubles only | Unverified live compatibility |
| Browser keyboard/a11y and perceptual audio quality | Usable controls and correct pronunciation | React/audio player | Tests/build passed; no screen-reader/listening run | Partially verified |

## Reviewed areas

Upload/auth/API authorization, project deletion, artifact restore, OCR routing
and checkpoints, text validation, segmentation/prosody contracts, provider
selection, resumable synthesis, WAV validation, mastering publication,
frontend pipeline controls, database models, migrations, and local test/build
configuration.

## Not fully reviewed

Live provider behavior, production reverse-proxy/TLS setup, multi-worker
deployment, large-book performance, password-entry support for encrypted PDFs,
screen-reader behavior, and perceptual pronunciation/audio quality. These need
external services, deployment access, or human listening.
