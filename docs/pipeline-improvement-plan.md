# Audiobook pipeline improvement plan

Date: 13 September 2026  
Priority order: correctness and recovery → editorial review → performance at book scale → maintainability and extension.

## 1. Recommendation and scope

Evolve the existing FastAPI/React application into a revision-based editorial production system. Keep the working extraction, segmentation, pronunciation, synthesis and assembly code, but put durable execution, explicit quality gates and immutable revisions around it. A generated MP3 must become a **review candidate**, not a completed production. Completion requires a recorded editorial decision tied to the exact audio, transcript, source PDF and configuration reviewed.

Deliver a usable final-review workspace early: source PDF beside the final audio and transcript, timestamped comments, explicit approval, and “Request changes” links into earlier stages. Initially support manual page anchors; add precise automatic navigation as provenance becomes available. Do not delay basic review until word alignment or every architecture improvement is finished.

This plan is based on static inspection of the current working tree, including `api.py`, `src/pipeline_v3.py`, database models, artifact helpers, OCR, segmentation/parser, both speech-planning stacks, synthesis/cache runner, provider adapters, audio assembly/mastering, React workflow/player/authentication, launch/configuration files and representative tests. The existing `docs/architecture-review.md` was cross-checked against implementation. External research used primary documentation, linked beside the relevant recommendations.

No application code, production data or configuration was changed for this review. Tests, live providers, browser behavior, throughput and real-book audio quality were not executed or measured. Findings below are code observations or explicitly identified design inferences. Proposed performance targets and estimates require baseline validation; they are not claims about current performance.

Assumptions: Hindi/Sanskrit source fidelity is essential; deployment begins with a small editorial team on one host; books may contain hundreds of pages and thousands of chunks. A reviewer can initially be an assigned editor, with optional independent approval for higher-assurance publishing. Actual team size, hardware, provider quotas, budget and distribution requirements remain implementation inputs.

## 2. What exists and what needs attention

Current flow:

`PDF → combined OCR text → reviewed text → source segments → phonetics → WAV chunks → mastered MP3`

FastAPI owns authentication, allocation, project routes, file mutations, audit records and stage execution. SQLAlchemy stores users/projects/artifact metadata, with SQLite by default. Numbered files hold active production state. React infers the available workflow from status strings and artifact flags. CLI calls the same `ProjectManager`, but bypasses API locking and audit behavior.

### Safeguards to preserve

- Synthesis fingerprints include narration inputs, provider and voice; resume verifies WAV content and digest.
- Provider failure is explicit; missing narration is not replaced with silence.
- Master assembly checks all expected chunks in script order and uses temporary output before replacement.
- Changed upstream saves invalidate active downstream artifacts; identical text/segment saves preserve work.
- Segmentation bounds long text without cutting oversized Devanagari tokens blindly; unresolved OCR markers are rejected by segment validation.
- API project access checks assignment; tests cover important corruption, retry, authorization and invalidation scenarios.

### Evidence and consequences

| Priority | Code evidence | Consequence and planned response |
| --- | --- | --- |
| P0 | `api.py:run_stage`, `project_lock`: in-process locks, background Audio task; OCR and Mastering execute within requests | Restarts lose execution ownership; multiple processes/CLI can race. Introduce persisted jobs, leases and fenced publication. |
| P0 | `src/db/models.py`: Project has one status string; no review, decision, job or revision entities | Completion, generation and human acceptance are conflated. Separate artifact readiness, job state and editorial state. |
| P0 | `frontend/src/ProjectPipeline.jsx`, final step: “Production Complete”, audio/download only | No stored confirmation, review comments or correction lifecycle. Replace with candidate review and controlled release. |
| P0 | `api.py:save_artifact_record` commits file-history metadata separately; mutation routes update files before final DB commit | File state and DB state can diverge after failure. Publish immutable output through a transactional pointer and reconciliation process. |
| P0 | `get_mastered_audio` relies on `_get_project_artifacts`; master readiness checks existence and current chunk metadata | The final MP3 has no independent digest or build lineage. Validate and fingerprint the master itself before review/release. |
| P0 | `ProjectManager.run_stage_1_segmentation` falls back to raw OCR; CLI `--all` proceeds through all stages | Human review is guidance rather than an enforced gate. Enforce approved-input requirements centrally, including CLI. |
| P0 | `ProjectPipeline.jsx` synchronizes fetched content into local edit state; nonempty-only segment effects; whole-list saves have no base version | Refetches can overwrite unsaved work; empty invalidated results can leave stale local rows; simultaneous edits can be last-write-wins. Add revision checks and explicit draft state. |
| P1 | `ocr_engine.extract_text_from_pdf`: serial page calls joined into one string | No persisted page checkpoints or downstream source anchors. Persist page/block results and resume individual pages. |
| P1 | `pipeline_v3.py`: sequential `chunk_0001` IDs; `runner.fingerprint` hashes the entire item, including ID and pauses | Earlier insertion shifts later identities; pause-only edits unnecessarily change speech cache keys. Introduce stable identity and separate speech/assembly fingerprints. |
| P1 | `runner.synthesize_segments`: one coroutine per item, full manifest rewritten on transitions | Large books produce growing scheduling and serialization overhead; repeated full-manifest writes scale approximately quadratically in chunk count. Use bounded consumers and per-item progress records. |
| P1 | `api.py:list_projects`, `_get_project_artifacts`: per-project file parsing/stat checks and assignee queries | Dashboard cost grows with all project chunks. Use paginated DB summaries with targeted integrity checks. |
| P1 | `ProjectPipeline.jsx` maps every segment to `WaveSurferPlayer`; each player loads a URL | Potential simultaneous fetching/decoding and excessive memory on large books. Use one shared player, virtualized rows and precomputed peaks. |
| P1 | `assembler.py`, `audio/enhancer.py`: nonempty MP3 check, fixed filter chain; no persisted measurements/timeline | No measured delivery acceptance or final timestamp provenance. Add decoded validation, QC report and assembly timeline. |
| P1 | `providers.py`: `gemini` actually uses Google Cloud TTS; Google adapter applies rate but not pitch/volume | UI settings can imply unsupported behavior. Publish provider capabilities and version the effective configuration. |
| P1 | `api.py`: default JWT secret, query-token media, editable process-wide provider settings; `AuthContext.jsx`: localStorage token | Shared hosting needs explicit bootstrap, safe session/media access and durable settings; any authenticated user currently can change global provider environment values. |
| P2 | Two planning/config/pronunciation stacks; large API and workflow component; numeric CLI/API/UI stage offsets | Behavior drifts and additions touch too many layers. Consolidate contracts and migrate incrementally behind shared services. |
| P2 | Broad Python minimum requirements; frontend lint script calls `eslint` while manifest lists `oxlint`, not ESLint | Reproducibility and clean-install checks need repair. Pin tested dependencies and configure an actual lint tool. |

## 3. Proposed editorial workflow

Use a small number of understandable editor-facing stages, with technical substeps visible on demand. Distinguish **saved**, **validated**, **reviewed**, **approved**, **running**, **failed** and **stale**. Completing a machine operation does not approve its output.

| Stage | Work and useful additions | Exit gate | Where issues return |
| --- | --- | --- | --- |
| 1. Intake and source check | Validate PDF, page count, rotation, readability, embedded text; record title/language, intended page range, chapter outline and narration exclusions | Every source page accounted for as included, intentionally excluded or pending; valid source revision | Replace source or fix page selection |
| 2. Transcription and source review | Checkpoint OCR per page; compare PDF/text; flag uncertain passages, columns, missing lines, page continuations, footnotes and duplicate headers | Included pages explicitly reviewed; no unresolved blocking source issues | Page OCR retry or manual transcription |
| 3. Structure and narration plan | Review chapters, heading levels, prose/verse/gloss, segment splits, joins and reading order; distinguish printed content from narration policy | All included blocks represented in order or explicitly excluded with a reason | Text review or structure editing |
| 4. Pronunciation and voice review | Show original text and spoken form; dictionary overrides, prosody, pauses, capabilities; preview representative prose and Sanskrit verses | Approved narration config and resolved blocking pronunciation issues | Dictionary override, phonetics or source |
| 5. Generate and inspect audio | Durable chunk generation, partial playback, focused retry, automatic diagnostic flags, optional spot review | All required speech assets current and technically valid; blocking QC issues resolved | Individual narration segment/provider setting |
| 6. Assemble and measure candidate | Ordered lossless assembly, pauses, timeline, final encoding, loudness/peak/duration report | Immutable candidate and validated QC report; all expected content accounted for | Audio, boundary pauses or mastering profile |
| 7. Final editorial review | PDF + transcript + actual final candidate audio; comments, bookmarks, listening progress, chapter decisions; request changes or confirm | Explicit candidate approval; no open blocking issues; required review scope satisfied | Any earlier stage via an anchored correction request |
| 8. Release and archive | Export approved version, chapters/metadata/checksums; record release notes and approval | Release refers to the approved bytes and revision; export verified | New revision for post-release corrections |

Stage 5 spot review is risk-based and can be lightweight. Stage 7 is mandatory for release. Avoid requiring every editor to listen to every chunk twice. For the initial policy, require explicit chapter review confirmations and a final attestation; listening telemetry helps resumption but cannot prove attention or comprehension. Any reduced review policy must be explicitly recorded for that candidate.

The production CLI must stop at human gates unless an authorized review decision already exists. Retain an explicitly marked draft/diagnostic mode for experiments; its outputs cannot become releases without normal approval.

## 4. Final-review workspace: first-class product requirement

### Layout and interaction

- A persistent header shows book, candidate revision, reviewer, status, saved state, open blocking issues and review progress. “Review candidate” replaces the premature completion banner.
- Left pane: PDF page, zoom, rotate, page thumbnails and printed page label versus PDF page index. Start with the existing PDF embed and manual page selection; move to a controlled viewer when interactive anchors arrive.
- Center pane: searchable transcript grouped by chapter, with source text authoritative and pronunciation text available separately. Selecting a mapped passage seeks to the corresponding audio interval and source page.
- Bottom transport: one persistent player for the final candidate, speed control, ±5/10-second seek, loop selection, keyboard shortcuts, chapter navigation and resume position. Changing UI panels must not interrupt playback.
- Right pane or drawer: comments, filters, checklist and decisions. Keep narrow screens usable through tabs and a persistent transport. Use readable Devanagari fonts, generous line spacing, explicit focus states and accessible labels.
- A comment action captures the current audio timestamp automatically. Editors may add a range, page/region, quoted passage, category, severity, assignee and suggested correction. Permit book-level comments when an exact anchor is unavailable.
- Decisions: **Approve candidate**, **Request changes**, **Save review for later**. Show why approval is blocked and link each blocker to its resolution. Preview/download remains available to authorized editors, clearly marked as an unapproved candidate; release export is gated separately.

PDF.js provides programmatic PDF page rendering; use that control for selection and overlays after the initial manual-anchor release. This is an implementation choice, not an automatic text-to-audio alignment solution. [PDF.js examples](https://mozilla.github.io/pdf.js/examples/)

### Review semantics

Each review session references a fixed candidate ID, source revision, transcript revision, narration revision and reviewer. Every decision records actor, timestamp, candidate digest, checklist version and optional summary. A second reviewer can have a separate session on the same candidate. Default roles are contributor, reviewer and release manager, implemented as project memberships/capabilities; a small team may assign multiple capabilities to one person.

An issue is a discussion thread, not a mutable note: retain comments, changes in severity, assignments, proposed fixes and resolution history. Suggested lifecycle: `open → acknowledged → fix_proposed → ready_for_recheck → resolved`, with `reopened` and `dismissed_with_reason`. An editor proposing a correction does not automatically resolve its review issue. Reviewers must listen/check again against the replacement candidate.

Approvals remain valid historical facts about old candidates. They never silently transfer to a new candidate. A new candidate always needs final approval, although unchanged chapter review evidence may be carried forward explicitly when its exact audio and source lineage match. A mastering-profile change affects the listening experience across the book and requires broader re-review.

Approval and release must atomically check current candidate identity, applicable review policy and open blocking issue count. Concurrent comments, edits and decisions must serialize through a candidate-level version/transaction so a late blocking issue cannot race with release. Issues found after release start an erratum/new revision and may mark the release withdrawn according to policy; retain the old record.

### Correct-and-return example

1. Reviewer hears a Sanskrit pronunciation error at 12:43 while viewing PDF page 18 and opens a blocking pronunciation issue.
2. “Fix pronunciation” opens the relevant segment and spoken-form override, carrying the issue ID and return location.
3. Editor previews the proposed change. The impact panel identifies the affected speech asset, candidate/chapter rebuild and review invalidation before saving.
4. Saving creates a revision; the existing candidate remains playable. Only affected speech is regenerated, then the candidate is rebuilt and its timeline recalculated.
5. The issue moves to ready for recheck and links the old/new audio intervals. Reviewer compares the correction and neighboring transitions, resolves the issue and approves the replacement candidate when all gates pass.

For a missing line, return to source transcription instead. For a misplaced verse boundary, return to structure. For excessive silence, return to pauses/assembly. For whole-book distortion or loudness, return to mastering. Navigation alone never deletes downstream artifacts; saving a changed revision marks affected descendants stale.

## 5. Target architecture and consistency model

Keep one modular application codebase with separately supervised API and worker processes. Use PostgreSQL for shared production, SQLAlchemy repositories, local immutable artifact storage initially, and a storage interface that can later support object storage. SQLite remains a local/demo profile with a single durable worker and atomic job claims; do not imply it has PostgreSQL row-lock behavior.

```text
React editorial workspace ── typed HTTP API ── application services
                                      │              │
                               authorization      workflow/revisions/reviews
                                                     │
                                           PostgreSQL + immutable storage
                                                     │
                                           durable worker entry point
                                                     │
                          OCR / narration adapters / media processing / QC
```

### Durable execution

Start with a DB-backed job queue because project revisions, job creation and audit events can share one transaction. Separate worker execution from requests; return `202` with job ID, accepted revision and status URL. PostgreSQL documents `FOR UPDATE SKIP LOCKED` as useful for queue consumers; it must be combined with leases and publication checks, not treated as complete job durability. [PostgreSQL SELECT locking](https://www.postgresql.org/docs/current/sql-select.html)

FastAPI's background-task guidance suggests larger job tools for work across processes/servers. The relevant conclusion here is to remove production work from API process lifetime; adopting Celery is an alternative if the team already operates a broker. Do not deploy both a custom queue and a broker at the outset. Reconsider the queue choice if routing, scheduling or operational maintenance outgrows the modest DB worker. [FastAPI background-task caveat](https://fastapi.tiangolo.com/tutorial/background-tasks/#caveat)

Required mechanics:

- Job states: queued, running, retry_wait, cancellation_requested, cancelled, succeeded, failed, superseded. Persist phase, completed/total units, attempt count, next retry time, safe error details and heartbeat.
- Claim jobs in a short transaction. Execute outside the transaction. Heartbeat and renew a lease. Reclaim expired jobs under bounded retry policy.
- Use a monotonically increasing fencing token for each claim. An expired worker may finish writing its private temporary output, but cannot publish after a new owner has claimed the job.
- Snapshot input revision IDs and effective config at submission. Promote results only if the expected input/candidate generation remains current; otherwise retain them as superseded history/cache.
- Idempotency keys deduplicate request retries; a unique logical operation key prevents duplicate active jobs for the same project, stage and input signature. Repeated delivery may execute work more than once, but must publish only one accepted result.
- Retry transient provider/network/rate-limit errors with jitter and a ceiling; respect Retry-After where available. Fail fast on invalid credentials, unsupported configuration and malformed source. Show an actionable recovery option.
- Cancellation stops claiming units and terminates managed subprocesses where possible. A timed-out thread/external call can keep running; enforce SDK deadlines and isolate non-cooperative work. Late output cannot publish after cancellation.
- All CLI mutations go through these services/job submission. During migration, forbid mixed legacy/new writers for a project.

### Revision and artifact publication

Use immutable revisions and explicit active pointers instead of deleting the only active view on edits. An artifact records checksum, byte size, media type, schema version, storage key, generating job, source/config fingerprints and validation status. Timestamps/usernames are labels, not identity or integrity guarantees.

Publication protocol:

1. Create a revision/job record transactionally with actor and expected parent revision.
2. Write output to an isolated temporary location; close, flush and apply the durability policy for the deployment. Validate content and compute digest.
3. Move/upload to a unique immutable storage key. Never overwrite another job's accepted bytes.
4. In a DB transaction, verify the lease token and expected revision, add lineage/QC records, update active pointer and job state, and append audit/event records.
5. A crash before DB publication leaves an unreferenced object; reconciliation removes it after a grace period or resumes verified publication. A missing/corrupt referenced object blocks release and raises a repair issue.

The filesystem and database cannot share an ordinary transaction. Explicit orphan handling, backups and restoration tests are part of the design. Preserve published objects and review references during garbage collection; failed temporary files and unreferenced caches may expire under configurable retention.

### Source provenance and stable identity

Persist `source PDF revision → page → block → segment revision → speech asset → candidate timeline interval`. Pages carry both physical PDF index and printed label. Block anchors hold page references, source offsets and optional normalized bounding boxes. A segment may span multiple blocks/pages.

Use stable opaque segment IDs plus a separate ordering field; insertions do not renumber the book. Record split/merge ancestry. Editorial identity and speech-cache identity are different: identical text may reuse an audio blob, while each repeated occurrence retains its own review anchors.

Do not fabricate region confidence or word timestamps. With today's OCR response, page provenance can be exact but bounding boxes are unavailable. Add manual regions first or an evaluated region-aware extraction adapter later. When mapping after edits is ambiguous, preserve the old anchor and request re-anchoring instead of attaching a comment to the wrong passage.

### Minimum data model

| Entity | Essential fields/constraints |
| --- | --- |
| Project / Membership | Stable project ID, display name, active revision/candidate, user capability assignments |
| SourceRevision / Page / BlockRevision | PDF artifact, page index/label, disposition and reason, extraction config, canonical text, provenance |
| TranscriptRevision / Chapter / SegmentRevision | Parent revisions, stable identity/order, source spans, semantic kind, exclusions, split/merge ancestry |
| NarrationRevision / ConfigRevision | Source revision, spoken form, explicit overrides, resolved voice/provider parameters, dictionary/profile versions |
| Job / JobItem / JobEvent | Operation/input signature, lease/token, attempts, state, progress, error classification, timestamps |
| Artifact / ArtifactDependency | Immutable storage key/digest, type/schema, inputs, producing job, integrity/QC status |
| Candidate / TimelineEntry / QCReport | Ordered artifact references, master digest, pause-inclusive sample/time intervals, measurements, build signature |
| ReviewSession / Issue / Comment / Decision | Candidate revision, reviewer, anchors, severity/state, discussion history, checklist/decision version |
| Release | Approved candidate and decision IDs, metadata/export artifacts, checksums, release/withdrawal history |

Use project IDs as foreign keys rather than relying on project names. Store UTC timestamps. Define deletion/retention behavior explicitly. Add versioned migrations before these tables; Alembic fits the existing SQLAlchemy stack. Baseline existing installations and exercise upgrade/rollback procedures on copies. [Alembic migration tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)

## 6. Performance plan without weakening integrity

### Highest-return changes

1. **Separate speech and assembly cache keys.** Speech keys include effective spoken input, provider/model/voice, supported rate/pitch/volume, adapter version and output format. Assembly keys include ordered speech digests, pauses, chapter layout and mastering/encoder profile. A pause-only change rebuilds assembly without a TTS call. Provenance changes still create new editorial revisions even when speech is reusable.
2. **Checkpoint OCR by page.** Cache by PDF/page digest, render/preprocessing parameters, OCR model/prompt version. Process independent pages with bounded concurrency; retain source order when composing. Start conservatively and measure quotas, cost and page quality. Re-OCR one page without replacing unrelated reviewed text.
3. **Use bounded work queues.** Replace gather-over-all-chunks with a fixed number of consumers. Configure per-provider and whole-system concurrency, separate network work from CPU/media slots, and schedule fairly across books. Give short editor previews a bounded priority lane so bulk generation cannot block corrections indefinitely.
4. **Persist progress per unit.** Job items update independently; maintain small transactional aggregate counters. Export a manifest snapshot at checkpoints/completion rather than rewriting a growing whole-book JSON on every transition. Retain current JSON readers during migration.
5. **Make status cheap.** Paginate projects/segments/issues; filter assignments in SQL and eager-load assignees. Read job counters and revision readiness instead of scanning every file on every dashboard request. Start with adaptive polling of compact job status; add resumable server events only when measured demand warrants it.
6. **Load only visible media.** Virtualize segment lists, keep one active transport, and generate waveform peaks server-side per artifact. WaveSurfer documents browser memory limits for large-file decoding and recommends predecoded peaks; this directly supports avoiding a waveform instance for every chunk. [WaveSurfer documentation](https://wavesurfer.xyz/docs/)
7. **Stream and bound media work.** Keep existing chunked PCM assembly. Add byte/range delivery tests, revision-specific URLs and ETags. Avoid fully downloading/decoding a multi-hour book just to start playback. Replace whole-chunk PCM reads in validation with bounded blocks where profiling justifies it; combine digest/validation passes when safe.
8. **Budget storage and time.** Preflight temporary disk requirements for PCM, mastered output and concurrent jobs. Mono 24 kHz 16-bit PCM is about 173 MB/hour before other copies. Prefer chapter-sized intermediate jobs for very long works; use a validated large-file-capable container if a PCM intermediate approaches RIFF/WAV limits. Replace a universal ten-minute timeout with measured, bounded stage-specific deadlines and progress monitoring.

Keep full integrity validation at artifact ingestion/publication and before release; validate cached reuse against trusted immutable identity and integrity policy. A metadata-only status check must never itself authorize release. Benchmark redundant disk passes before optimizing them away.

### Performance acceptance targets

Establish a reproducible fixture matrix: 20/200/500 PDF pages, mixed scanned/embedded text, 100/1,000/5,000 speech segments, short and multi-hour masters. Include a 10,000-segment metadata/UI stress fixture. Record hardware, filesystem, browser, concurrency, provider configuration and warm/cold cache conditions.

| Proposed target | How to measure |
| --- | --- |
| Job acceptance p95 under 500 ms; project/status reads p95 under 300 ms on agreed host | 10 concurrent editor sessions during configured background load; exclude upload transfer and provider completion time |
| First usable review screen under 2 s and seek response under 1 s on agreed local/LAN setup | Real browser with a multi-hour candidate; cached and uncached cases reported separately |
| No speech requests for pause-only changes or unchanged verified retries | Provider call-count assertions and job telemetry |
| Single-segment pronunciation edit regenerates only affected speech | Compare artifact digests and executed job items before/after; candidate re-encoding remains expected |
| Recovery within two lease periods after worker loss | Kill/restart worker mid-page, mid-chunk and before publication |
| Browser memory remains bounded as segment count grows | Compare 1,000 vs 10,000 rows; same visible-row/player bound, no eager full-book audio fetch |
| Throughput increases without higher failure/cost rates | Sweep provider concurrency 1/2/4 where quotas permit; measure pages/minute, audio real-time factor, retries and cost per completed hour |

Do not set a universal TTS completion SLA before measuring provider behavior. Track editor correction-to-review time as a primary product metric alongside generation throughput.

## 7. Quality, review gates and operational reliability

### Automated checks

- Intake: real PDF validation at upload, page count/rotation/encryption checks, explicit selection/exclusion inventory, resource limits and actionable failure messages.
- Source: unresolved markers, empty required pages, malformed semantic tags, suspicious duplicates, inconsistent reading order and source-span coverage. Draft saves may retain unresolved issues; approval/generation gates enforce resolution. Preserve the current conservative OCR prompt as a versioned baseline.
- Narration: provider-specific length limits on the effective spoken payload, supported languages/voices, numeric prosody bounds, dictionary version and overridden spellings. Source fidelity remains separate from TTS pronunciation convenience.
- Audio: existing PCM/digest checks plus clipping, unexpected silence, outlier duration and boundary diagnostics. Structural checks cannot prove that every word was spoken.
- Candidate: decode final output, verify duration against assembly timeline with codec tolerance, verify expected segment coverage/order and measure integrated loudness/true peak. Preserve a lossless master for subsequent exports.
- Use a measured mastering process and save its report. FFmpeg `loudnorm` supports measured parameters and linear/dynamic modes; evaluate a two-pass profile and remeasure the encoded delivery. Current -18 LUFS/-1.5 dBTP values are project defaults to audition, not an asserted distribution standard. [FFmpeg loudnorm documentation](https://www.ffmpeg.org/ffmpeg-filters.html#loudnorm)

The timeline starts from actual PCM sample counts and both pause fields. Reconcile it with the encoded file's playback timing, including encoder delay. Segment/page synchronization is the first target; word highlighting requires evaluated alignment and must be labeled approximate where necessary.

### Human evaluation and later assistance

Create an expert-reviewed Hindi/Sanskrit corpus containing prose, shlokas, glosses, archaic spelling, difficult conjuncts, visarga, vowel signs, mixed punctuation, footnotes and page-spanning passages. Measure transcription errors and pronunciation/pacing judgments separately. Compare proposed dictionary/provider/mastering changes against this corpus before rollout.

ASR/forced alignment may later flag likely omissions, repeats and suspicious durations. Evaluate false positives on Sanskrit and old Hindi first; route findings to humans. Do not automatically rewrite sacred text, resolve source ambiguities or approve a book using ASR agreement.

### Deployment and support

- Use explicit administrator setup; disable unattended public first-user bootstrap for shared deployment. Validate secrets at startup, scope settings updates, centralize configuration and redact tokens/provider secrets from logs.
- Serve frontend/API/media under a configured common origin. Prefer HttpOnly secure session cookies for browser/media use, with CSRF protection for mutations; retain scoped bearer credentials for CLI if needed. If signed media URLs are required, use short-lived, artifact-scoped tokens instead of the account JWT.
- Supervise API/workers with clean shutdown, readiness/health checks and disk/database/provider diagnostics. Replace port-killing launch scripts with process ownership and clear occupied-port errors.
- Log structured job/project/revision/segment IDs and classified errors. Track queue age, heartbeat age, retry/failure rates, cache hits, provider latency, worker memory, temporary disk use and blocked reviews. Never log full private manuscripts by default.
- Back up database and immutable storage consistently; verify checksums and perform restore drills on another directory/host. Initial proposed objectives: recover acknowledged editorial changes within a one-hour backup window and restore service within four hours; validate cost/operational feasibility before adopting them.
- Distinguish provider outage from application failure. Preserve drafts and completed work when credentials expire, network drops or quota is exhausted. Show retry timing and the affected units.

## 8. Maintainability and extension boundaries

Extract services around use cases before splitting every file. Suggested boundaries:

```text
src/domain/          revisions, workflow transitions, review decisions, typed contracts
src/application/     submit job, save draft, approve stage, build candidate, release
src/infrastructure/  database repositories, artifact storage, provider adapters
src/workers/         claims, leases, execution, recovery, resource limits
src/api/             routers, request/response schemas, authentication
src/extract/         extraction implementations and page validation
src/normalize/       canonical segmentation and explicit pronunciation transformations
src/synthesis/       speech generation, assembly and measured QC
frontend/src/features/{projects,source,narration,review,jobs}/
```

These are target boundaries, not an instruction to move every file immediately. Keep `ProjectManager` as a compatibility facade while extracting one tested use case at a time. Replace free-form dictionaries at boundaries with versioned request/response schemas. Generate TypeScript API types from OpenAPI, then migrate the main workflow components incrementally. A single stage registry supplies stable named IDs, labels, prerequisites, permissions and progress units; API/CLI/UI numerical offsets become legacy adapters.

Split `ProjectPipeline.jsx` into workspace shell, stage views, revision-aware draft hooks, shared API client, job status and review controls. Show save errors near the draft; prevent query refresh from resetting dirty forms; handle project-route changes and empty server results explicitly. Persist drafts by user/project/base revision, with visible saved/pending/conflict states. Use optimistic concurrency (`If-Match` or an explicit base revision); return a conflict with a diff instead of overwriting another editor.

Consolidate `core/types.py`, the alternate synthesis config/models and both pronunciation/planning implementations through characterization tests. Keep one canonical speech contract and provider-specific translation at adapters. The shared XML parser already participates in the active segmenter; do not delete the entire alternate directory under the assumption that all of it is unused. Determine `Editor.jsx` reachability before retirement.

Define narrow extension interfaces:

- Extraction provider: page input + config → text/blocks/provenance + diagnostics.
- Speech provider: validated effective narration request → audio + actual provider metadata/timing where available.
- QC check: immutable artifact set → diagnostic findings, with version/severity and no hidden source mutation.
- Exporter: approved candidate + export profile → verified delivery artifacts.
- Storage: immutable put/get/range/stat/integrity operations, independent of project filenames.

Provider capability metadata must declare supported parameters, limits, formats, locales, timing support and retry semantics. Rename `gemini` to `google_cloud_tts` through a backward-compatible configuration migration. Unsupported settings should be disabled/explained or rejected; never silently change narrator/provider. Defer arbitrary user-defined workflow engines and dynamic plugin loading until concrete needs demonstrate value.

Pin tested Python dependencies and runtime versions; retain `package-lock.json` and use clean installs. Repair lint configuration, add Python formatting/static checks, and use CI for offline tests, frontend build/lint and migration checks. Document schema versions, artifact formats, error codes and recovery procedures alongside code.

## 9. Prioritized delivery backlog

Effort bands are engineering effort, not elapsed promises: S = roughly 1–3 days, M = 4–8 days, L = 2–3 weeks, XL = 3–5 weeks for a focused owner, excluding waiting for editorial feedback. Re-estimate after the baseline and first vertical slice. QA and editorial acceptance are part of each item.

| Order / ID | Deliverable and owner | Dependencies | Effort | Acceptance / exit condition |
| --- | --- | --- | --- | --- |
| 1 / P0-A | Baseline fixtures, architecture decisions, schema migration foundation — backend + QA | None | M | Existing behavior characterized; upgrade of copied existing DB tested; agreed fixture/metric baseline recorded |
| 2 / P0-B | Typed workflow, immutable artifact/candidate revisions and safe publication — backend | A | L | Crash before/after publication cannot expose mixed revisions; stale/invalid master cannot be approved; history remains readable |
| 3 / P0-C | Durable jobs for OCR/audio/mastering and shared CLI path — backend/operations | A, B contracts | L | Restart/duplicate/cancellation/lease-expiry tests pass; job errors persist; late workers cannot publish |
| 4 / P0-D | Final-review MVP: PDF, final audio, manual page/time comments, decisions and change requests — frontend + backend + editor | B; may proceed alongside C | L | Editor completes review → request changes → correction → replacement candidate → recheck → approval; old decision cannot approve replacement |
| 5 / P0-E | Safe drafts, revision conflicts, explicit human gates and gated release — frontend + backend | B, D | M | Refetch cannot overwrite dirty work; conflict returns diff; CLI/API cannot bypass gates; only approved bytes enter release |
| 6 / P0-F | Shared-host configuration, sessions/media authorization, backups and supervision — operations + backend | A–C | M | Safe startup/bootstrap; authorization on candidate/issues/media; clean worker restart; successful restoration drill |
| 7 / P1-A | Page/block provenance and per-page OCR checkpoint/review — backend + frontend | B, C, E | L | Failure on page 73 retains 1–72; rerun only missing/stale page; exclusions and manual corrections survive retries |
| 8 / P1-B | Stable segments, dependency graph, separate speech/assembly caches — backend | B, P1-A | L | Insertions preserve unrelated identities; pronunciation edit calls TTS only for affected speech; pause-only edit calls none |
| 9 / P1-C | Candidate timeline, synchronized review and issue re-anchoring — frontend + backend | D, P1-A/B | L | Transcript-to-page/audio navigation works; ambiguous anchors are visible; old/new issue intervals are inspectable |
| 10 / P1-D | Bounded workers, per-item progress, DB summaries and scalable media UI — backend + frontend | C; B for media identity | M–L | Agreed large-book load targets pass; no full-manifest write per transition or eager thousands-player load |
| 11 / P1-E | Measured mastering/QC, lossless master and expert reference evaluation — audio/backend + editor | B, C, timeline contract | M–L | Decoded candidate and metrics validate; false-positive diagnostics assessed; reference corpus accepted |
| 12 / P2-A | Consolidated models/services, TypeScript boundaries, reproducible CI — backend + frontend | Begin touched-code cleanup in P0; consolidate after P1 contracts settle | L | One canonical speech contract; frontend/API stage definitions agree; clean install/build/checks pass |
| 13 / P2-B | Chapter exports, review assignments, version comparison and restoration UI — full stack + editor | Stable candidates/reviews/provenance | M–L | Chapters navigate/export from approved revision; restore creates a new draft with correct stale descendants |
| 14 / P3-A | Evaluated alignment/ASR assistance, additional providers/storage, advanced scheduling — specialist/full stack | Measured P1/P2 demand and corpus | Separate spikes | Each addition proves quality/operational value and passes adapter contracts before rollout |

Release slices:

1. **Reliable review pilot:** P0-A through P0-F. Final-review MVP should be demonstrated as soon as B/D are usable; do not wait for later synchronization features. Shared-host pilot requires C/E/F as well.
2. **Efficient book production:** P1 items. Page recovery, targeted corrections, synchronized review and measured audio acceptance make long books practical.
3. **Maintainable editorial platform:** P2, with P3 only when justified by real usage.

Keep refactoring inside feature slices where possible. Avoid making a whole-codebase rewrite a prerequisite for editor value.

## 10. Failure and editorial scenario acceptance matrix

| Situation | Required behavior | Verification |
| --- | --- | --- |
| Worker/API dies during OCR or synthesis | Recover expired job; reuse committed page/chunk output; show interrupted/retrying state | Process-level kill test, not only provider mocks |
| Two users click Generate or client retries after a lost response | Same logical job returned; no duplicate accepted candidate | Concurrent submissions/idempotency test |
| Lease expires while provider call continues | Old worker output cannot replace current result | Delayed worker with fencing assertion |
| Editor changes source while a job runs | Job keeps snapshot; result becomes superseded if inputs no longer current | Save-versus-publish race test |
| Two editors save the same passage | Second stale save becomes an explicit conflict; both drafts preserved | Two browser contexts |
| Refetch returns empty segments after invalidation | Stale local segment/phonetics data cannot be resubmitted as current | UI state regression test |
| PDF contains a blank, missing, rotated or unreadable page | Explicit disposition/review; no silent omission or whole-book endless retry | Mixed-page PDF fixtures |
| A verse crosses pages or chapter reading order is wrong | Multi-page provenance and explicit structure correction preserve source | Expert-approved corpus case |
| Provider times out, returns corrupt audio or ignores content | Technical errors block completion; suspected omissions become review findings | Provider doubles plus human listening evaluation |
| Only pauses change | Reuse speech assets; rebuild timeline/master and require replacement-candidate approval | Zero TTS calls; changed timeline assertion |
| Comment timestamp moves after a source correction | Keep old anchor; map by stable segment where possible; flag ambiguous mapping | Split/merge/delete/reorder cases |
| Reviewer approves while a new blocker is submitted | Serialize decision and issue mutation; no release with an unresolved blocker | Transactional concurrency test |
| Disk fills or DB commit fails after output creation | No half-published candidate; actionable job failure; reconciler handles orphan | Inject write/commit failures |
| User loses assignment or session expires | Deny future protected reads/mutations; preserve unsaved draft for authorized recovery | Role change/media range tests |
| An already released book needs a correction | Keep prior release; open new revision and review cycle; optional withdrawal record | Release history/replacement test |
| Large book or slow editor device | Partial loading, persistent player, bounded resource use and clear progress | Real-browser large-fixture profile |
| Backup must restore onto another host | Revisions, comments, approvals and audio digests remain consistent | Restore drill with release integrity check |

## 11. Test and rollout strategy

Keep existing offline integrity tests as regression coverage. Extend behavior tests around gates, revisions, source fidelity and failure recovery. The current `test_e2e_pipeline.py` skips real OCR and mocks final mastering bytes; it is useful integration coverage, not proof of browser workflow or valid end-to-end delivery. The current ProjectPipeline frontend test checks rendering rather than the edit/review lifecycle.

Add focused layers:

- Domain tests: legal transitions, invalidation scope, approval identity, source coverage and split/merge mapping.
- Repository/service tests: migration preservation, optimistic concurrency, job claims/fencing and crash-safe publication against production-like PostgreSQL.
- Worker tests: real process termination, persisted retry state, cancellation and resource ceilings.
- Media tests: small real FFmpeg fixtures, decoded final output, sample/timestamp accounting, pause boundaries and corruption rejection.
- Browser tests: upload/review/generate/comment/fix/recheck/approve/export, reconnect, unsaved drafts, conflict handling and media seeking.
- Editorial acceptance: representative Hindi/Sanskrit books reviewed by actual editors; compare time spent fixing an issue and navigating between source/audio.
- Optional scheduled live-provider canaries with budget limits; keep default CI offline and credentials independent.

Migration sequence:

1. Back up the database and project tree; inventory artifacts and compute baseline digests without modifying active files.
2. Introduce versioned migrations and new tables additively. Import existing numbered artifacts as legacy revisions with known/unknown lineage explicitly marked.
3. Do not invent page provenance, approvals or integrity status for legacy masters. Existing MP3s become unapproved legacy candidates; validate and review before release.
4. Pilot one small and one long book through new services while preserving the legacy artifact reader. Make writer ownership explicit per project.
5. Route all API and CLI writes to new services; old numeric stage routes become documented compatibility adapters. Remove mixed writer access.
6. Validate restoration and rollback using a copy. Application rollback must preserve newly created reviews/artifacts; do not downgrade away production review records. Prefer forward repair once new schema data is in use.
7. Expand to the team after the full correction loop, restart recovery and authorization tests pass. Remove obsolete code only after usage and compatibility evidence support it.

## 12. Decisions to settle during implementation

These do not block the initial architecture/review work, but each needs an owner and recorded answer before its dependent release:

| Decision | Working default | Settle by |
| --- | --- | --- |
| Independent reviewer required? | Same editor may approve in small-team mode; independent review configurable per project | P0 review policy acceptance |
| Source exclusions and footnotes | Explicit page/block disposition with reason; never silently omit | Intake/source-review design |
| Distribution format and loudness | Retain current MP3 option; audition current profile and validate actual destination requirements | Export/QC profile acceptance |
| Production scale/host | One host, PostgreSQL, supervised API + bounded workers, local immutable storage | Durable-job deployment |
| Preferred provider and cost ceiling | Existing explicit selection retained; preview and quotas visible; no silent fallback | Provider capability/preflight work |
| Retention and recovery objectives | Keep released/reviewed revisions; expire unreferenced cache under policy; proposed backup targets in section 7 | Shared-host pilot |
| Synchronization granularity | Exact segment/page provenance first; manual anchors for legacy material; word alignment later | P1 review synchronization |

The first success criterion is concrete: an editor can compare a PDF against the actual final audio, record a problem, return to the correct earlier stage, regenerate only necessary work, recheck the replacement, and approve a reproducible release—even after a worker restart or a competing edit.
