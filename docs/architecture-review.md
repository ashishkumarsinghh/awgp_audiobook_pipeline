# Architecture and quality review

## Current architecture

[api.py](file:///home/ashish/projects/awgp_audiobook_pipeline/api.py) owns authentication, allocation, project CRUD, durable job submission, artifact/audit records, stage orchestration, review workflows, and candidate management. [src/pipeline_v3.py](file:///home/ashish/projects/awgp_audiobook_pipeline/src/pipeline_v3.py) is the CLI entry point and shared [`ProjectManager`](file:///home/ashish/projects/awgp_audiobook_pipeline/src/pipeline_v3.py#L30-L280). SQLAlchemy/SQLite stores project, user, job, artifact, and review metadata, while numbered files under `projects/` hold active and historical artifacts. React/Vite with TanStack Query provides PDF/text review, editing, waveform playback, and asset downloads.

The flow is PDF -> OCR text -> reviewed text -> semantic segments -> pronunciation/prosody -> WAV chunks -> MP3 mastering. OCR renders pages with PyMuPDF and sends images to Google GenAI (or falls back to embedded text extraction). [`SemanticSegmenter`](file:///home/ashish/projects/awgp_audiobook_pipeline/src/normalize/segmenter.py) consumes XMLParser heading/subheading/prose/gloss/shloka blocks. [`PronunciationDictionary`](file:///home/ashish/projects/awgp_audiobook_pipeline/src/normalize/pronunciation.py) and [`ProsodyPlanner`](file:///home/ashish/projects/awgp_audiobook_pipeline/src/normalize/prosody.py) transform a narration copy. Edge TTS is the primary provider; Google Cloud TTS (`gemini` / `google`) provides high-fidelity studio voice output. [`AudioEnhancer`](file:///home/ashish/projects/awgp_audiobook_pipeline/src/synthesis/audio/enhancer.py) applies FFmpeg broadcast-standard processing (loudnorm, de-essing, noise reduction).

A second experimental planner/SSML stack under `synthesis/speech` and `synthesis/ssml` has separate config dataclasses and unit tests but is not wired into `ProjectManager`.

## Implemented Architecture & Quality Improvements

| Finding | Consequence | Implemented Response |
| --- | --- | --- |
| TTS failure substituted silence | Missing words appeared successful | Explicit errors, validated PCM, and resumable manifest. |
| Mastering skipped unavailable chunks | Incomplete books could be delivered | Require every expected chunk matching current script and voice. |
| Cache relied on existence/size | Edits reused old narration | Input fingerprints and SHA-256 audio digests. |
| Shell-interpolated media commands | Fragile paths and unchecked failures | Argument-list subprocess wrapper and PCM assembly. |
| Invalid PDFs invoked models without page images | Hallucinated text appeared valid | Reject invalid PDFs before OCR; reject 0-byte file uploads. |
| Local/empty cloud responses omitted pages | Silent source loss | Page-specific errors and consistent page limits. |
| Chunk limit checked after append | Oversized requests and unstable pacing | Hard word-boundary bounds across semantic blocks. |
| Sentence regex discarded punctuation runs | Changed intonation/verse endings | Preserve punctuation and decimals. |
| UI polled the wrong synthesis status | Progress froze | Consistent status and durable chunk error display. |
| Ambiguous source/phonetics target | Edits left mismatched artifacts | Separate source endpoint and downstream invalidation. |
| Project routes lacked assignment enforcement | Editors accessed other books | Shared route authorization, lock manager, and audio authentication. |
| Username admin granted privilege | Later signup elevated itself | First-account bootstrap only; hardened username and password validation. |
| Background work captured request ORM state | Fragile lifetime and test isolation | Scalar actor identity and request database bind. |
| Artifact restoration left DB status stale | Reverted projects retained completed status | Synchronize `Project.status` with restored artifact stage. |
| TTS provider change desynchronized status | Invalidated audio while project remained "Mastered" | Reset `Project.status` to `03_Phonetics` on provider/voice changes. |
| N+1 queries in dashboard listing | Degraded response times as project count grew | Batch fetch assigned users and aggregate `ReviewIssue` counts in single DB queries. |
| Path verification vulnerability via `startswith` | Potential prefix collision path traversal | Secured paths via `os.path.commonpath` checks against canonical project roots. |
| Google Cloud TTS crashed on `rate=None` | Unhandled `AttributeError` during synthesis | Safe parsing with `getattr(segment, "rate", None)` and fallback to 1.0. |
| Outdated migration script omitted schema columns | Migration missed `book_identifier`, `display_name`, `recording_type`, `language` | Updated `scripts/migrate_db.py` to inspect and migrate both `projects` and `users` tables. |
| Broken frontend linting script | `npm run lint` failed due to missing ESLint configuration | Switched `frontend/package.json` lint script to `oxlint` (runs 104 rules with 0 errors). |
| Dead unrouted prototype code | `Editor.jsx` used obsolete 4-stage numbers and unauthenticated fetches | Removed dead `frontend/src/Editor.jsx` file. |
| Process-local background execution | Worker crashes lost in-flight stage ownership; multiple API workers could overlap work | Added durable `Job` records, DB project leases, worker heartbeats, expired-lease reclamation, job polling, and independent stage submission. |

## Remaining Gaps & Recommendations

1. **Human Quality Assurance & Listening Corpus:** Structural checks verify file integrity and length bounds, but cannot prove pronunciation correctness or verify that a speech engine articulated every phoneme accurately. Build a curated Hindi/Sanskrit reference test corpus for automated and listening regression testing.
2. **Per-Page OCR Checkpoints & Provenance:** No per-page checkpoints, bounding-box coordinates, or confidence scores are persisted during long OCR jobs. If OCR is interrupted, it must re-process the PDF. Storing page-level intermediate JSON artifacts would make OCR fully resumable.
3. **Queue backend scale:** Durable DB-backed jobs and leases now support multiple API workers and crash recovery. SQLite still serializes writes and is not the preferred high-throughput production queue; use PostgreSQL and consider a dedicated queue when job volume or provider concurrency requires it.
4. **Database Schema Versioning:** The database relies on `Base.metadata.create_all()` and manual migration scripts (`scripts/migrate_db.py`). Integrating Alembic for declarative, version-controlled schema migrations will streamline future migrations.
5. **Chapter Splitting & Streaming Master:** Currently, the entire book is mastered into a single `06_mastered.mp3` file. Adding chapter-based MP3 export with ID3 metadata, embedded cover art, and cue points will enhance distribution readiness.
6. **Production Auth & Secrets:** Development now uses a cryptographically random in-process JWT fallback, so tokens expire on restart when `JWT_SECRET_KEY` is unset. Production deployment still requires a configured shared `JWT_SECRET_KEY` across workers, HTTPS termination, and non-query-string media token passing.
