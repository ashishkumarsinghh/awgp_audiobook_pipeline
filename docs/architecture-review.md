# Architecture and quality review

## Current architecture

api.py owns authentication, allocation, project CRUD, artifact/audit records and stage orchestration. src/pipeline_v3.py is the CLI entry point and shared ProjectManager. SQLAlchemy/SQLite stores project/user metadata, while numbered files under projects/ hold production artifacts. React/Vite with React Query provides PDF/text review, editing, waveform playback and downloads.

The flow is PDF -> OCR text -> reviewed text -> semantic segments -> pronunciation/prosody -> WAV chunks -> MP3. OCR renders pages with PyMuPDF and sends images to Google GenAI; without a key it reads embedded text. SemanticSegmenter consumes XMLParser heading/subheading/prose/gloss/shloka blocks. PronunciationDictionary and ProsodyPlanner transform a narration copy. Edge is the primary provider; the historical Gemini adapter actually calls Google Cloud TTS. AudioEnhancer applies FFmpeg processing.

A second planner/SSML stack under synthesis/speech and synthesis/ssml has separate config dataclasses and tests but is not wired into ProjectManager. Unifying these models requires a deliberate migration rather than replacing working stages now.

## Highest-impact findings and changes

| Finding | Consequence | Implemented response |
| --- | --- | --- |
| TTS failure substituted silence | Missing words appeared successful | Explicit errors, validated PCM and resumable manifest |
| Mastering skipped unavailable chunks | Incomplete books could be delivered | Require every expected chunk matching current script and voice |
| Cache relied on existence/size | Edits reused old narration | Input fingerprints and SHA-256 audio digests |
| Shell-interpolated media commands | Fragile paths and unchecked failures | Argument-list subprocess wrapper and PCM assembly |
| Invalid PDFs invoked models without page images | Hallucinated text appeared valid | Reject invalid PDFs before OCR |
| Local/empty cloud responses omitted pages | Silent source loss | Page-specific errors and consistent page limits |
| Chunk limit checked after append | Oversized requests and unstable pacing | Hard word-boundary bounds across semantic blocks |
| Sentence regex discarded punctuation runs | Changed intonation/verse endings | Preserve punctuation and decimals |
| UI polled the wrong synthesis status | Progress froze | Consistent status and durable chunk error display |
| Ambiguous source/phonetics target | Edits left mismatched artifacts | Separate source endpoint and downstream invalidation |
| Project routes lacked assignment enforcement | Editors accessed other books | Shared route authorization and audio authentication |
| Username admin granted privilege | Later signup elevated itself | First-account bootstrap only |
| Background work captured request ORM state | Fragile lifetime and test isolation | Scalar actor identity and request database bind |
| Live scripts collected as unit tests | Offline suite failed | Explicit testpaths and boundary mocks |

Small modules now own atomic artifacts/segment validation (core/artifacts.py), checked media I/O (synthesis/audio/io.py), and synthesis/cache orchestration (synthesis/runner.py). Existing artifact names and CLI stage numbers remain stable. Unrelated user changes were retained.

## Remaining gaps

1. **Human quality assurance.** Structural checks cannot prove OCR accuracy or that a provider spoke every word. Build a reviewed Hindi/Sanskrit reference corpus and listening evaluation. ASR/alignment may flag omissions, but needs evaluation before automatic corrections.
2. **OCR provenance and recovery.** No per-page checkpoints, coordinates or reading-order confidence are persisted. Interrupted OCR repeats earlier pages. Blank pages require review. Model text is not compared with image regions.
3. **Durable jobs.** Locks and background tasks are single-process. Multiple workers/concurrent CLI/API operations are unsupported. A durable job table or queue with leases is needed for shared production hosting. OCR and mastering are synchronous API requests.
4. **Database evolution.** create_all does not migrate tables. scripts/migrate_db.py now adds missing TTS columns with a SQLite backup and is safe to rerun; the checked local database required this migration. Introduce versioned migrations before further schema changes.
5. **Persistence consistency.** Atomic files avoid truncated writes, but filesystem updates and DB records are not one transaction. Copies can remain after DB failures. History exists without a first-class restoration workflow.
6. **Provider capabilities.** The legacy Gemini label does not describe its Google Cloud implementation and lacks complete Edge pitch/volume parity. Add capability metadata and consistent persisted config before exposing more engines. No live provider availability, credentials or output quality was verified.
7. **Pronunciation governance.** Alias, schwa and visarga rules need expert examples, versioning and per-project overrides. Keep original spelling authoritative and normalization an explicit editorial choice.
8. **Chapters and measured mastering.** Headings survive, but output is one MP3 without chapter navigation. Add chapter export, measured loudness/true-peak reports and listening acceptance. Filter targets are not certification or measured quality guarantees.
9. **Deployment.** Development JWT defaults, first-user bootstrap, query-string media tokens, localhost assumptions and port-killing launchers are local-use assumptions. Configure secret management, same-origin serving and administrative bootstrap before wider hosting.
10. **Maintenance.** Python requirements are broad minimums without a lockfile or configured linter/type checker. The API remains large with duplicated stage labels. Extract typed services incrementally. Retire or integrate unused Editor.jsx and the second SSML planner.

## Validation approach

Offline tests use temporary project directories, in-memory SQLite, provider doubles that produce WAVs, and deliberate provider/corruption failures. Tests assert artifacts and resulting state. Real FFmpeg smoke tests exercise short silence and signals. Frontend validation uses Vitest and the production build. Exact observed final results are recorded in the task report.
