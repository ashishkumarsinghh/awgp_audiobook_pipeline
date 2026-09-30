# Audiobook corrections: architecture audit and implementation handoff

Date: 2026-09-30. Reviewed commit: `5457d8aa8ebcb379b3145c967cafdd9eeb4fe407`, plus the working-tree proposal. The initial implementation pass described at the end of this document has now been applied; the remaining tickets are still pending.

## 1. Outcome and scope

Keep the existing pipeline, but make reviewer corrections durable inputs to a revisioned build. Reuse verified speech assets by their actual synthesis request, independently of page numbers, segment order, and assembly pauses. Publish a new review candidate with a source snapshot and timeline; preserve the prior candidate and its feedback.

The desired loop is:

1. A checker listens to candidate A and writes a page/paragraph/phrase correction on paper.
2. An editor enters the note, selects the exact passage against the PDF, and chooses source correction, pronunciation, pacing, or regeneration.
3. The system previews the affected passage and reports what will be reused or regenerated.
4. Applying the correction persists it independently of generated files.
5. Rebuilding performs no OCR unless explicitly requested and synthesizes only changed speech requests. Assembly may still process the whole book.
6. Candidate B carries forward unresolved feedback. The checker hears the replacement with adjacent context and explicitly verifies the fix.
7. Approval and delivery refer to the exact candidate reviewed.

For a word pronunciation fix, regenerate its existing containing segment initially. Do not introduce word-level audio splicing: it needs alignment and introduces audible joins. Preserve existing chunk boundaries unless the correction actually requires a split or merge. “Incremental” means bounded expensive OCR/TTS work, not a promise that a long MP3 can be remastered in seconds.

### Review basis and limits

Inspected the active `ProjectManager` path, OCR/cleaning/segmentation/prosody, synthesis providers/cache/mastering, artifact utilities, API mutation/job/review routes, DB models/migration code, React editor/player, and relevant tests. Cross-checked the older architecture documents and `feedback_architecture_proposal.md`. Alternate synthesis modules were inspected enough to identify a parallel planning stack; they were not independently audited end to end. Untracked experimental scripts are not assumed to be production entry points.

All executed probes used temporary fixtures and provider doubles. No real book was regenerated, no paid provider was called, and no production database was migrated. Live provider compatibility, perceptual pronunciation quality, production multi-process stress, and long-book benchmarks remain unverified. This is a local code review, not a current provider API survey.

### Implementation status after the first pass

Implemented and covered by regression tests: canonical stage-folder writes with legacy aliases, PDF-digest-bound OCR checkpoints and atomic manifests, safe full rebuild reuse of reviewed source, complete delivery invalidation, content-based speech fingerprints that ignore provenance/assembly-only fields, cycle-safe audio reuse, cleaner false-positive fixes for narrated “contents” and repeated refrains, stale-worker completion fencing, candidate-bound review playback/issues/decisions, and versioned exact-target correction preview/apply routes. The correction layer currently supports source replacement, pronunciation replacement/override, prosody and boundary pause updates; it is deliberately conservative and does not yet implement the full revision graph, immutable asset store, split/merge lineage, or frontend correction workspace described below.

### Existing foundations to preserve

- WAV format/content validation, digest checks, retries, and explicit failed chunks.
- Ordered streaming PCM assembly and temporary final-output replacement.
- Separate `source_text` and `pronunciation_text` fields.
- Page checkpoint files and `<metadata_page>` propagation already exist.
- Candidate MP3 copies, digest-checked candidate playback, review issues, and two distinct reviewer approvals already exist.
- Persisted jobs and lease heartbeat/recovery already exist, although ownership is not safely enforced.
- Project assignment checks and basic path containment.

Earlier documents contain outdated findings. Do not implement a second job queue, candidate system, or page-marker mechanism on the assumption that these features are absent. The older proposal also overstates guarantees: the speech fingerprint hashes more than text and pauses, `all` reruns OCR, and cache reorder reuse is unsafe. Do not infer page identity from footer text that the cleaner deliberately removes.

## 2. Verified baseline

Commands executed from this repository in Ubuntu/WSL:

```sh
venv/bin/python -m pytest -q
cd frontend && npm test -- --run
```

Backend: **119 passed, 3 failed**, 15.32 seconds. Frontend: **5 passed**, two test files. Tests are predominantly offline; `test_e2e_pipeline.py` mocks mastering with non-MP3 bytes and is not a real delivery validation.

| Existing failing test | Interpretation and required action |
| --- | --- |
| `tests/test_extract.py::test_ocr_engine_mocked` | Expected output predates `<metadata_page>1</metadata_page>`. Preserve the new provenance behavior and update assertions to test it. |
| `tests/test_extract.py::test_local_page_limit_and_scanned_page_error` | Same outdated text assertion; failure prevents this test reaching its later scanned-page check. Update the contract and retain that check. |
| `tests/test_integrity.py::test_upstream_change_invalidates_derived_artifacts` | Raw invalidation leaves the old cleaned text. Fix source/derived ownership; do not simply delete the assertion. Preserve human corrections before replacing derived clean text. |

Additional executed temporary probes:

| Probe | Observed current result |
| --- | --- |
| Write “Old passage.” to stage-folder cleaned text and “Corrected passage.” to root alias; force segmentation | Segments contain **Old passage.** |
| Create the named master, then `invalidate_after('phonetics')` | Named master still exists. |
| Synthesize A/B; reorder to B/A under the same sequential IDs | Unchanged A is synthesized again because copying B overwrites A's old cache slot. Digest checking prevents silent reuse of those wrong bytes, but reuse is lost. |
| Change only `page` in otherwise identical speech input | Fingerprint changes. |
| Repeat `<chant_refrain>Repeat these words</chant_refrain>` around prose | Second legitimate refrain disappears. |
| Clean `<prose>The contents of the box were precious.</prose>` | Entire passage disappears. |
| Replace a PDF's bytes, retaining checkpoint directory and book name | Extraction returns the previous PDF's checkpoint text. |
| Read checkpoint `ocr_manifest.json` after extraction | Empty file: undefined `pages` raises inside a swallowed exception. |
| Claim a job, expire its lease, reclaim with a new worker, finish using the old job identity | Old completion marks the reclaimed job succeeded and clears project ownership. |

These observations are reproducible without network services. Other findings below are marked as code-inspected risks, not claimed stress-test results.

## 3. Findings and required fixes

Priority definitions: **P0** can lose editorial work, omit narration, or publish/approve the wrong revision; **P1** blocks efficient reliable corrections; **P2** improves scale or maintainability. File/line references identify this snapshot; follow the named functions if lines move.

### F01 — P0: competing active files lose or ignore edits

Evidence: `api.py:836`/`:859` write root raw/clean files; `ProjectManager.run_stage_1_segmentation` (`src/pipeline_v3.py:314`) always prefers stage-folder cleaned text. Other stages choose aliases by mtime. `restore_artifact` (`api.py:1129`) also writes root-only. Construction of `ProjectManager` calls `_sync_audio_folders`, so even some GET paths copy files.

Impact: the UI displays a saved correction while segmentation consumes older text. Raw edits remain masked by existing cleaned text. Timestamp ties, restores, and independent CLI edits make ownership unpredictable.

Fix: introduce one artifact repository with one authoritative location per artifact. Stage folders are the canonical working layout; legacy names become compatibility exports only. Reads must have no filesystem mutation. Never use “newest mtime wins” to resolve disagreement. Migration must report diverging copies and preserve both until an editor chooses. All API/CLI saves and restores use the same repository/service.

Acceptance: edit through API, then segment through CLI and API; both consume the correction. Restore follows the same rule. Identical saves are no-ops; an ambiguous legacy import does not silently select a version.

### F02 — P0: regenerated stages erase manual corrections

Evidence: `run_stage_1_ocr` rewrites cleaned text from checkpoints; `run_stage_1_segmentation` regenerates positional IDs; `run_stage_2_phonetics` rebuilds all pronunciation/prosody. Both CLI and API `all` start with OCR (`pipeline_v3.py:920`, `api.py:_execute_queued_job`). API JSON saves permit modifying source within phonetics without a source-revision check.

`ai_audio_fixes.json` (`pipeline_v3.py:410`) is only a partial overlay: no schema/version/precondition; it is absent from freshness checks; errors become warnings; repeated text gets global replacement; the code tests `find_text` in source but replaces it after dictionary/prosody transforms, where it may no longer exist. It supports neither auditable source edits nor stable split/merge targets.

Fix: persist typed correction records independently of generated snapshots. Apply source corrections to a source revision, then derive segmentation/pronunciation, then apply explicitly scoped speech overrides. Never silently reset conflicting corrections. Add a `rebuild` command that starts at the earliest dirty dependency; `all` must preserve accepted correction inputs. Enforce source immutability in pronunciation-only API operations.

Acceptance: pronunciation override survives unrelated source edits and forced replanning; ambiguous targets block publication with a useful conflict. The original PDF and extraction remain available.

### F03 — P0: stale named masters can be served as current

Evidence: `invalidate_after` (`pipeline_v3.py:207`) omits `named_master_file`; `run_stage_4_mastering` checks output mtimes before validating chunks and ignores speed/EQ/metadata in its skip decision (`:534`). With no manifest it can still return an existing master. `_get_project_artifacts` and `get_mastered_audio` (`api.py:530`, `:1075`) test current chunks and a master's existence, not whether that master was built from those chunks.

Failure sequence: edit phonetics → old named master survives → regenerate chunks → master existence plus current chunks makes the old named MP3 eligible for download before new assembly. The survivor was reproduced; the download consequence follows from the inspected route.

Fix: immediately invalidate every active delivery alias and reject stale publication; retain history. Then replace existence/mtime freshness with an immutable build manifest and current pointer. Check expected build signature before any mastering skip or draft-master download. Validate final MP3 before committing a candidate.

Acceptance: after edits and after synthesis, draft-master download stays stale until assembly commits a matching build. Changing speed/EQ causes assembly; changing tags causes packaging, with zero TTS calls. Missing manifest cannot make an old master current.

### F04 — P0: job leases do not fence writes or completion

Evidence: `src/job_runner.py:claim_job` reads then mutates rows without conditional claim/row lock. `finish_job` does not accept worker identity. Lease renewal does not report lost ownership. `_execute_queued_job` reads mutable files/settings at execution and writes status without fencing. API mutation locks are process-local and the worker does not acquire them; CLI has no shared lock. Enqueue's active-job check is also check-then-insert.

Impact: even one API process can edit while its worker runs. Multiple workers can claim the same job; an expired worker can overwrite its successor. A snapshot of mixed source/settings can be published. A stale owner completing a reclaimed job was reproduced; simultaneous claim races were not stress-tested.

Fix: transactional claims, monotonically increasing fencing tokens, immutable input revision on every job, optimistic draft versions, and conditional publication/completion. SQLite must claim under an explicit write transaction (e.g. `BEGIN IMMEDIATE`) with conditional updates; do not assume a Python lock protects multiple processes. Keep expensive work outside DB transactions. For a future PostgreSQL deployment use its appropriate row-lock/conditional-update mechanism. A new queue product is not required.

Acceptance: two processes cannot both own a project; old worker completion/publication is rejected after reclaim; editing while generation runs creates a new revision and cannot publish the older result as current. Queue scan skips blocked projects so one busy project does not starve others.

### F05 — P0: feedback and approvals can refer to a different candidate

Evidence: review issue/decision requests omit candidate identity; handlers select latest pending candidate. Playback URL `/review/audio` also resolves latest on each request (`api.py:1167–1281`). A stale browser listening to A can submit feedback against B. Only pending candidates are superseded on a new build; identical-hash lookup can find a superseded candidate and not reactivate/select it correctly. Candidate records snapshot only MP3 filename/hash, not source, plan, settings, or timeline.

Issues are candidate-local and a new candidate gets no carried-forward unresolved issues. Resolution is a status toggle unrelated to a correction or replacement. Approval count includes every historical approval, even if a reviewer subsequently requests changes. Approval does not check candidate file integrity itself. Reopening an issue on an approved candidate does not revise its release eligibility.

Fix: explicit immutable candidate IDs/hashes in audio URLs and mutations; a current candidate pointer separate from historical approval status; candidate-bound source/plan/timeline snapshots; issue lineage across candidates; transactional approval gate. Preserve the existing policy of two distinct humans. New blockers/reopened issues and changes-requested decisions invalidate current approval eligibility; retain historical events. No review endpoint should silently substitute a candidate.

Acceptance: stale-A request cannot create a B decision; seeking A still plays A after B exists. B surfaces A's unresolved blockers. A resolved issue identifies the correction and the candidate on which a checker verified it. Approval refuses missing/tampered candidate bytes and concurrent blocker races.

### F06 — P0: extraction/cleaning can silently discard source content

Evidence: `_is_toc_block`, `_is_artifact_block`, `_find_repeated_furniture`, and `_remove_repeated_artifact_lines` in `text_cleaner.py` infer exclusions from content alone. Any `contents` substring can remove a block; short repeated non-punctuated text is treated as furniture regardless of semantic role. Cleaning runs again during segmentation. The English sentence and repeated-refrain losses above were reproduced.

The active OCR batch prompt is less strict than `_transcribe_page`'s long fallback prompt (`ocr_engine.py:207` vs `:267`): it mentions “allowed” tags without enumerating them or enforcing the same uncertainty contract. README describes `[???????]`, while validation recognizes `[अस्पष्ट]`; the cleaner can erase punctuation-only uncertainty markers before validation.

Fix: retain raw extraction, create explicit excluded-block decisions with reason and origin, and make aggressive heuristics suggestions requiring confirmation. Preserve chants, repeated narrative, footnotes, and uncertainty markers. Run a single defined cleaning transform, with provenance and tests for idempotence. Share one OCR prompt/schema/validator between normal and fallback paths; reject unexpected structure rather than narrating it. Canonical uncertainty is `[अस्पष्ट]`, with legacy markers imported as unresolved issues before cleaning.

Acceptance: source coverage accounts for each included or intentionally excluded block; repeated refrain survives; uncertainty blocks generation; footer fixtures still exclude confirmed furniture. Human source fidelity remains necessary even with technically valid audio.

### F07 — P1: page checkpoints are not tied to source or configuration

Evidence: `ocr_engine.py:66` keys checkpoints by book name/page only. `ocr_manifest.json` references undefined `pages` at `:131`, and the exception is swallowed after opening/truncating the file. Checkpoints are direct writes. `pages_to_process` silently filters invalid indexes, and a subset is assembled as the whole output. Blank/excluded pages disappear from the returned text without a coverage ledger. With credentials configured, embedded-text pages also use remote vision; without credentials, nonempty block presence can trigger a skip after all usable text was filtered.

Fix: cache by document digest, page index, extraction mode, model, prompt version, render settings, and exclusion config. Atomic page records include completion/blank/excluded/error status and digests. Validate page ranges; merge page retry output into the existing revision rather than replacing the book with a subset. Separate `sample` from full-book builds and never release a sample as complete. Add explicit `auto|embedded|vision` extraction policy per page; `auto` uses embedded text only after quality checks and records why it selected it.

Acceptance: replaced PDF cannot reuse mismatching checkpoint; crash cannot make partial text complete; single-page retry preserves all other pages and their corrections; intentional blank pages are accounted for. Old checkpoints with unknown source binding require explicit adoption against the source or re-extraction, not blind trust.

### F08 — P1: page/paragraph metadata is insufficient for paper feedback

Evidence: page markers and `SpeechSegment.page/paragraph` exist, but represent physical PDF page and parser-counted paragraph. Segment IDs remain `chunk_0001` order positions (`pipeline_v3.py:350`). No printed-page mapping, stable block/sentence IDs, source spans, or cross-page spans. Headings/blocks influence paragraph counts; the number is not guaranteed to match a checker's visual numbering.

Fix: physical PDF index, printed label, stable block/segment identity, ordered source spans, and an explicit paragraph-label convention. Page/paragraph are navigation hints, never sufficient edit identity. Reconcile unchanged blocks uniquely within page/context; do not use text hash as identity for repeated verses. Split/merge stores lineage and remaps or conflicts corrections.

Acceptance: two identical verses are independently addressable; inserting a sentence on page 1 does not retarget an issue on page 20; a passage crossing pages can be found from either page. Legacy unknown anchors remain visibly unknown.

### F09 — P1: audio cache identity is incomplete and overly broad

Evidence: `runner.py:fingerprint` excludes only `id`, so source labels, page/paragraph, and assembly pauses invalidate TTS. It omits provider instance model/pace and adapter version; e.g. Studio `self.model` and Sarvam `self.model/self.pace` are outside the key. Reuse copies old ID paths over one another while still reading those paths (`synthesize_segments`), as reproduced by swapping two chunks. Only the latest manifest is indexed; old variants cannot be reliably reused on revert. Corrupt manifest records can also fail outside schema validation.

Fix: immutable content-addressed speech assets plus a mapping from segment IDs to asset keys. Hash the **effective provider request** and output/adapter contract, not the entire editorial record. Separate speech, assembly, and delivery keys. Keep verified prior variants, enabling correction undo. Import legacy assets conservatively with known/unknown config provenance.

Acceptance: reorder, page-label change, or boundary-pause change causes zero TTS calls; one spoken-text change calls TTS only for affected requests; model/voice/effective rate changes invalidate correctly; swap and cyclic permutation cannot overwrite reusable source assets; corruption is rejected. Reuse means byte-identical stored audio, not deterministic reproduction from a remote model.

### F10 — P1: prosody dependencies expand edits and ignore some controls

Evidence: `ProsodyPlanner.apply_prosody` infers paragraphs from neighbor pauses, not actual paragraph IDs, and varies pitch with index across runs. An early insertion can change many later requests. It replaces zero pauses with defaults even when the segmenter uses zero to avoid a mid-sentence pause. `run_stage_2_phonetics` does not populate page/paragraph in `SpeechSegment` before planning. Assembler ignores `pause_before_ms`; active providers do not consume that field. Google Cloud sends rate but not segment pitch/volume; Studio ignores all three; Azure strips inline phoneme/break markup. These are observed adapter behaviors, not claims about upstream service capabilities.

Fix: explicit boundary kind and pause intent; local paragraph-scoped prosody; distinguish unset pause from explicit zero. Publish adapter capability metadata and reject or visibly explain unsupported controls. Treat boundary pauses in assembly and inline speech pauses in the request. Define one owner for each boundary, e.g. effective gap = max(previous after, next before), with first/last handling; do not sum both blindly. Implement and test that policy consistently.

Acceptance: splitting a long sentence does not insert an unrequested pause; local edits do not change distant paragraph prosody; unsupported pitch/phoneme operations cannot report a successful audible fix. Desired provider controls need explicit adapter work and a later live smoke test.

### F11 — P1: speed changes compound and timeline evidence is missing

Evidence: mastering already applies default 1.15x. `run_stage_5_speed` preferentially reads the named, already sped MP3 and overwrites it, so repeating the command compounds tempo and lossy encoding. A nominal `mastered_1.0x_original.mp3` fallback is never established by this path. Assembly persists no segment offsets or measured delivery mapping.

Fix: retain immutable lossless base assembly; derive target speed once from it. Store build parameters and timeline alongside each candidate. Use sample counts for unprocessed boundaries; map through tempo/filter/encoder behavior and validate with decoded fixtures. Show approximate timing explicitly where exact mapping is unavailable. Word timestamps require alignment and are optional later work.

Acceptance: speed 1.10 twice produces the same target duration within encoding tolerance, not 1.21 of the starting tempo; boundary/segment seek lands in the intended passage; changing one earlier duration updates later times in B without changing A's timeline.

### F12 — P1: frontend cannot execute the paper correction loop safely

Evidence: `ProjectPipeline.jsx:167` submits only body/severity/integer timestamp. No structured page/paragraph/expected/replacement fields, candidate identity, correction preview, or before/after recheck. Effects at `:217` overwrite local edits on refetch and ignore empty segment/phonetics arrays. Whole-array saves lack a base revision. Stage success means enqueue success but navigates immediately; completion refresh is specialized to audio. Segment/source edits can survive locally after server invalidation and be submitted again.

Fix: revision-aware draft state, dirty/conflict handling, named stage/job states, completion-driven refresh for every stage, and a focused correction workspace. Add structured note entry, passage search, proposed patch preview, “regenerate affected audio,” and checker verification. Preserve unsaved text during conflicts; disable applying an old draft as current.

Acceptance: background refetch cannot erase typing; empty invalidated results clear clean local state; dirty stale drafts remain recoverable but cannot silently overwrite newer work; queued work is not shown as completed.

### F13 — P1: artifacts lack an atomic publication boundary

Evidence: CLI history filenames have second resolution (`save_timestamped_artifact`), so repeated saves can overwrite history. Invalidation deletes after ignoring backup failures. API artifact save commits independently of candidate/status changes. Restore uses direct copy without validating the historical content first. DB schema changes occur at API import as well as in a separate migration script.

Fix: UUID/content-addressed immutable objects; validated staged files followed by an atomic DB pointer transaction. Never delete a user's only valid copy after a backup failure. Introduce explicit versioned migrations and a reconciler for orphan objects/missing files. Restore creates a new revision, never mutates historical records. Keep DB and filesystem backups consistent.

Acceptance: disk-full/commit failure leaves the last valid candidate reachable; interrupted restore does not replace active input with partial bytes; two history writes in one second survive; migrations are additive/idempotent and tested on copied legacy schema.

### F14 — P1: provider choices and configuration disagree across entry points

Evidence: voice catalog includes Sarvam and Studio, but API provider validators allow only Edge/Google/Azure/Gemini (`api.py:428`, `:1293`). CLI supports more providers and has a different default voice. Global settings mutate per-process environment for any authenticated user and do not persist a reproducible project configuration. Stage freshness does not include dictionary or `ai_audio_fixes.json` changes.

Fix: one provider registry for CLI/API/UI, canonical provider aliases, provider-specific defaults/capabilities, and persisted project synthesis configuration. No silent process-environment changes to existing projects. Resolve config once into each revision/job, including dictionary digest and model/adapter version. Administrative default changes affect new projects explicitly.

Acceptance: every displayed provider is selectable with a valid default; unsupported selection is rejected consistently; fresh worker and CLI resolve the same project settings; dictionary edits replan but only changed effective requests trigger TTS.

### F15 — P2: book-scale work and maintenance need bounded costs

Evidence: synthesis creates one task per segment and rewrites the entire manifest repeatedly; mirrored audio duplicates storage; GET paths can copy it. Per-row `WaveSurferPlayer` creation can fetch/decode many clips. Two planning/pronunciation stacks and the large API/component duplicate responsibilities. Numeric stages differ: CLI OCR=0 versus API OCR=1. Current Python requirements mostly specify lower bounds.

Fix after correctness: bounded worker consumers and per-asset progress updates, one shared/lazy audio player, paginated source/segment queries, named stages with numeric adapters, and one active planning service. Measure before chapter caching or infrastructure expansion. Pin a tested environment/lockfile after resolving compatibility, not by indiscriminately upgrading dependencies.

Acceptance: benchmark 1,000-segment synthetic build with zero paid calls, report memory/manifest-write volume/cache hit count; UI only loads selected audio; existing CLI/API aliases retain documented behavior.

### F16 — P2: deployment/auth concerns remain separate from editorial fixes

Evidence: first public signup becomes admin (`api.py:264`), random JWT secret is per-process when unset, and long-lived auth tokens appear in media query strings. Existing assignment protects projects, but bootstrap and multi-worker media authentication deserve deployment-specific hardening.

Fix before shared deployment: explicit bootstrap/admin creation, required shared production secret, and scoped short-lived media access or authenticated fetch/cookie flow. Do not let these additions displace correction correctness. Preserve authorization on new correction/candidate/source endpoints. No deployment was inspected in this audit.

## 4. Target contracts: use these decisions during implementation

### 4.1 One source of truth and publication protocol

Retain Python/FastAPI/SQLAlchemy and the current UI. Use the existing database for revision metadata, correction events, job state, and active pointers. Use immutable files for larger source/plan/audio manifests and media. CLI must call the same application service and database as API, including project registration for CLI-only legacy projects. Do not add a second authoritative YAML store. A JSON correction file may be an import/export format.

Suggested layout (new paths; migrate before switching writers):

```text
projects/<project>/
  source/<pdf_sha256>.pdf
  revisions/<revision_id>/source.json
  revisions/<revision_id>/segments.json
  revisions/<revision_id>/speech_plan.json
  audio/assets/<request_sha256>/<take_id>.wav
  builds/<build_id>/assembly.wav
  builds/<build_id>/timeline.json
  builds/<build_id>/manifest.json
  builds/<build_id>/delivery.mp3
  imports/legacy/<import_id>/...
```

An asset key identifies an effective synthesis request; `take_id` distinguishes intentional regenerations of that same request. Ordinary rebuild reuses the selected verified take; “regenerate this bad performance” creates a new take and records its selection without forcing every segment. Keep asset content digest distinct from request digest.

Publication protocol:

1. Capture immutable revision/config and expected draft version; enqueue with idempotency key.
2. Claim job with `(job_id, worker_id, fence)`; compute in unique temporary paths.
3. Validate files and atomically rename into unique immutable object paths.
4. In a short DB transaction verify ownership/fence and expected revision; insert build/candidate and switch current pointer together. If draft advanced, retain an explicitly stale/historical result without making it current.
5. Finish only under matching ownership. Lost lease means stop publishing; a background provider thread may finish but cannot affect active pointers.
6. Reconciliation reports orphan files or unavailable objects; never guesses a current build from filenames. GC is deferred and must retain objects referenced by candidates, corrections, active jobs, or releases.

### 4.2 Minimal additive database changes

Use versioned migrations; keep existing tables and identifiers during rollout.

| Entity | Required additions/new fields |
| --- | --- |
| Project | `draft_revision_id`, `current_candidate_id`, `released_candidate_id`, integer `version`, persisted config reference; generation state separate from editorial state |
| ProjectRevision (new) | ID, project, parent, source PDF digest, source/plan manifest paths and hashes, config snapshot/hash, schema versions, author, created time, provenance status |
| Correction (new) | ID, project, base revision, origin issue, type, target JSON, operation JSON, reason, author, supersedes/reverts ID, created time; accepted records immutable |
| CorrectionApplication (new) | correction ID + revision ID unique, outcome `applied|conflict|superseded`, affected IDs, before/after digest, conflict details |
| AudioAsset (new) | request digest, take ID, content digest, relative path, format/duration, effective provider config, verification state; unique request/take |
| Build (new) | ID, revision, assembly/delivery signatures, immutable manifest/timeline/media references, validation state, creating job/fence |
| Candidate (existing) | build/revision binding, predecessor ID, immutable source and timeline access; migrate old lineage as unknown |
| ReviewIssue (existing) | origin candidate, root issue/parent link, revision-bound source anchor, correction link, verification candidate/reviewer/time; distinguish `fixed_pending_check` from `verified` |
| ReviewDecision (existing) | candidate hash/review version precondition; retain events and compute effective current decisions, not count all approvals ever |
| Job (existing) | input revision/config, fence, expected project version, idempotency key, claim ownership; enforce one active project operation transactionally |

Use constraints/indexes for project scope and uniqueness. Validate cross-project references in the service as well as DB constraints. Enable/test SQLite foreign-key enforcement before relying on it; update deletion/retention behavior explicitly. Migrate legacy `resolved` to a historical resolution state; do not invent checker verification evidence.

### 4.3 Source document and stable identity

`source.json` schema version 1 should contain document digest, total pages, selected-page scope, and an ordered page list. Each page has:

- `page_id`, **one-based** `pdf_page`, nullable `printed_label` (string: `१२`, `iv`, `12a` are valid), extraction method/config/digest, and coverage status.
- Ordered blocks with stable `block_id`, raw extracted text, corrected source text, semantic type, inclusion/exclusion reason, and optional genuine bounding boxes. Do not fabricate boxes for OCR output without geometry.
- Display paragraph labels and stable identities separately. Define the default count as included narrative paragraphs per physical page, with headings separate. Editors can correct labels; label changes do not affect speech.
- Segment `source_spans`: ordered `(page_id, block_id, start, end)` entries. Use half-open Unicode code-point offsets in the exact referenced block revision; JavaScript must convert from UTF-16 indexes. Never slice inside a Devanagari grapheme cluster. Preserve raw text separately if normalizing working text.

New IDs are persisted UUIDs, independent of ordering and hashes. Existing UUID remains for a one-to-one edited block. Split/merge creates explicit parent lineage and new IDs where identity is no longer one-to-one. Re-extraction reconciliation uses page/neighbor/quote evidence and accepts only unique mappings. Mark ambiguity as conflict. A paragraph continuing across pages can have multiple source spans; physical page boundaries must not automatically imply spoken pauses.

Legacy combined text without trustworthy markers gets unknown anchors plus a manual mapping interface. Do not rerun the whole book just to manufacture provenance. Known source IDs and cache reuse are separate concerns.

### 4.4 Correction schema and application rules

Example import/API payload (illustrative IDs/digest):

```json
{
  "schema_version": 1,
  "base_revision_id": "rev_A",
  "origin_candidate_id": 42,
  "origin_issue_id": 103,
  "kind": "pronunciation_replace",
  "target": {
    "block_id": "block_uuid",
    "segment_id": "segment_uuid",
    "pdf_page": 16,
    "printed_label": "12",
    "paragraph_label": "2",
    "start": 10,
    "end": 14,
    "expected_text": "शब्द",
    "expected_block_sha256": "<digest of exact base block>"
  },
  "operation": {"replacement": "<confirmed spoken form>"},
  "reason": "Checker sheet 3, note 7"
}
```

Required kinds: `source_replace`, `pronunciation_replace`, `pronunciation_override` (whole segment), `prosody_set`, `boundary_pause_set`, `segment_split`, `segment_merge`, `regenerate_take`. Exclusion changes are source inclusion decisions with explicit reason, not empty text replacement. Project dictionary rules are a separate explicitly broad-scope operation showing affected occurrences.

Rules:

1. Every change has a base revision, expected target text/hash, exact scope, and human-readable reason. API derives actor/time server-side. Page/paragraph/quote search proposes targets; it never applies an ambiguous replacement.
2. First version defaults to one exact occurrence. Support “all occurrences in this project” only with an explicit preview/count and a separate scoped rule. Never apply global `str.replace` accidentally.
3. Source corrections create a new corrected source revision. Pronunciation edits change only the speech layer. For source-span pronunciation overrides, compose literal spans and transformed spans deterministically; do not locate a source phrase by searching already-transformed dictionary output. Store a source-to-speech span map or conservatively conflict on overlapping dictionary/prosody edits.
4. Generated dictionary/prosody defaults precede explicit whole-segment human overrides. Segment-level human fields override automatic defaults. Conflicting overlapping accepted patches require an explicit superseding correction; no hidden last-write-wins.
5. Applying the same correction to the same base is idempotent. Rebuild materializes from the revision graph/correction applications; it must not apply replacements twice to already corrected text. Undo creates a new event/revision and can select an older cached asset.
6. Validate schema, allowed fields, provider capability, pause bounds, unresolved text, and all target matches before committing a batch. First version batches are atomic. Malformed imports fail with line/item diagnostics, not warnings followed by generation.
7. Import `ai_audio_fixes.json` and existing edited phonetics into draft corrections with an import report. Preserve original files. When generated baseline/config is unavailable, keep legacy plan overrides as explicitly scoped records with unknown origin; do not claim an inferred pronunciation diff is source truth.

### 4.5 Dependency and cache signatures

Use canonical serialized inputs with schema/algorithm versions. Do not include timestamps or editorial labels in speech signatures.

| Key | Inputs | Exclusions |
| --- | --- | --- |
| Extraction | PDF digest, page, extraction mode/model/prompt/render/exclusion settings | book display name |
| Source/plan | parent source revision, accepted corrections, segmentation/prosody algorithm version, dictionary/config digests | runtime file mtimes |
| Speech request | canonical provider/model/voice/language, effective text or SSML, actual rate/pitch/volume/pace/options, adapter/request version, output format | segment ID/order, page labels, issue state, external boundary silence |
| Assembly | ordered asset content digests/takes, boundary gaps, mastering algorithm/settings, target tempo, output profile | paper note wording |
| Delivery | mastered audio identity, tags/packaging version and settings | approval status |

Define `provider.prepare_request(segment, config)` as the only transformation producing an immutable effective request. Hash that object and execute that same object, so hash logic cannot disagree with provider preparation. Unsupported controls fail or require an explicit acknowledged fallback; they must not be silently hashed as if effective.

Dictionary changes should invalidate planning, but only changed prepared requests invalidate speech. A boundary-pause edit rebuilds assembly only. Inline SSML break edits change speech. Changes in local segmentation/prosody may affect neighboring segments within the same paragraph; the rebuild preview must report that actual dependency set rather than promising exactly one chunk for every edit.

### 4.6 Shared service and API/CLI surface

Add small modules rather than rewriting `api.py` in one step:

```text
src/core/schemas.py              versioned validated contracts
src/core/project_store.py        canonical repository, revisions, legacy import
src/review/corrections.py        target resolution, preview, apply, conflict/undo
src/review/candidates.py         candidate lineage, issues, approvals
src/build/planner.py             dependency signatures and dry-run plan
src/build/service.py             shared save/build/publish workflow
src/synthesis/assets.py          immutable asset lookup/import/verification
```

Suggested service methods: `preview_correction`, `apply_corrections(expected_version, ...)`, `plan_rebuild(revision_id)`, `enqueue_build(revision_id, idempotency_key)`, `publish_build(job_owner, expected_version, ...)`, `verify_issue(candidate_id, ...)`. API and CLI call these methods; neither duplicates orchestration logic.

New routes (names may be adapted consistently):

- `GET /projects/{p}/source?pdf_page=16` and `GET /projects/{p}/passages?...` return stable targets plus revision.
- `POST /projects/{p}/corrections/preview` is read-only and returns matched passage(s), before/after text, conflicts, affected segment IDs, and work estimate.
- `POST /projects/{p}/corrections` includes expected project version; stale writes return 409 with current revision. Use a client idempotency key so retry cannot duplicate a note or correction.
- `GET /projects/{p}/rebuild-plan?revision_id=...` shows OCR/TTS/assembly/packaging reuse and reasons. `POST /projects/{p}/builds` runs the reviewed plan against that immutable revision.
- `GET /projects/{p}/candidates/{id}/audio|source|timeline` never resolves to a newer candidate.
- Issue/decision requests require `candidate_id`, expected candidate hash, and review version. Verification requires correction application and replacement candidate; dismissal requires reason.

Prefix with `/api` in the actual router. Enforce existing assignment checks on every new route. Keep old numeric stages as compatibility adapters to named `extract`, `segment`, `plan_speech`, `synthesize`, `assemble`, `package`. New commands are proposals, not currently available:

```sh
python run.py BOOK locate --printed-page 12 --paragraph 2 --quote '...'
python run.py BOOK corrections import notes.json --dry-run
python run.py BOOK corrections apply notes.json --expected-revision REV
python run.py BOOK rebuild --dry-run
python run.py BOOK rebuild
```

Use JSON initially (already supported); do not add YAML parsing merely because an older proposal suggested it. Manual paper entry is the MVP. Optional scanned-handwriting transcription creates **draft notes only**, attached to the original scan, and requires editor confirmation of the target and wording. It is not a dependency for the correction system.

### 4.7 Review and release behavior

Separate issue progression: `open → correction_proposed → fixed_pending_check → verified`, with `reopened` and `dismissed` paths. “Audio generated” is not “verified.” A carry-forward entry links to the original note, old timestamp, and old source anchor; the new candidate gets a mapped anchor or an explicit mapping conflict. Do not silently replace the old timestamp.

Unresolved blocking issues always carry forward. Default new workflow requires major pronunciation/source issues to be verified or explicitly dismissed before release; encode this policy visibly and preserve historical approvals during migration. Retain two different human reviewers for candidate approval. Decisions must be serialized against issue/candidate mutations and be effective for the current review version. A later changes request supersedes that reviewer's earlier approval; new blocking evidence invalidates approval eligibility for that review cycle.

Distinguish downloadable drafts for checking from released delivery. Add an explicit release endpoint/pointer that requires current candidate approval and integrity. Older approved release remains accessible by ID while edits proceed. An unchanged MP3 hash alone does not prove an identical reviewed source/config snapshot; candidate identity includes its build lineage. CLI-generated candidates must be registered through the same service.

## 5. Implementation tickets, in dependency order

Do one ticket at a time. Each ticket must leave passing targeted tests and no hidden migration of real books. The short-term repairs in T01–T03 are protective stepping stones, not a competing architecture.

### T00 — Capture failing behavior and baseline

Dependencies: none. Files: `tests/test_extract.py`, `tests/test_integrity.py`, new focused regression tests.

- Add failing regressions for F01, F03, F04 stale completion, F06 source loss, F07 checkpoint identity, and F09 reorder reuse.
- Fix only outdated extraction assertions to expect page markers; retain scan/error checks.
- Use temporary PDF/WAV fixtures and offline providers; distinguish wrong narration from unnecessary cache misses.
- Record current failures before implementation. Do not mark all green by weakening source/candidate checks.

### T01 — Canonical active artifacts and complete invalidation

Dependencies: T00. Files: new `project_store.py`, `core/artifacts.py`, `pipeline_v3.py`, API save/read/restore/status routes.

- Centralize paths; stage-folder files become authoritative after explicit import/conflict resolution.
- Route all reads/saves/restores through store; remove constructor mirroring and mtime selection.
- Preserve existing files before mutation; unique history names; failed backup blocks destructive invalidation.
- Include named delivery in invalidation and reject missing build evidence. Add temporary master-signature sidecar using current ordered chunks/settings until full Build entities land.
- Raw changes invalidate generated clean text only after preserving manual edits; do not leave stale clean authoritative. During migration require explicit resolution of clean-vs-raw conflicts.

Done: UI clean save reaches synthesis; no stale named master download; restore validation and alias divergence tests pass.

### T02 — Transactional jobs and mutation versions

Dependencies: T01. Files: `job_runner.py`, DB models/migration, API worker/save routes, CLI entry.

- Add project version and job fence/owner conditions; atomically claim and enqueue.
- Bind jobs to a captured immutable input bundle as an interim revision, never live mutable filenames.
- Extend executor/heartbeat/finish signatures with owner/fence; reject stale status updates and publication.
- Make API and CLI share locking/version rules; owner checks apply to filesystem publication as well as job rows.
- Test on file-backed SQLite using separate connections/processes, not only `StaticPool` in-memory sequential calls.

Done: simultaneous claim, stale worker, edit-vs-build, and blocked-project fairness tests pass. No long DB transaction spans a provider call.

### T03 — Source integrity and checkpoint repair

Dependencies: T01; coordinate publication with T02. Files: OCR engine, cleaner, segmenter, artifact validation, extraction tests.

- Fix undefined manifest variable and atomic checkpoint serialization.
- Add source/config digest binding, explicit page coverage and extraction selection; reject invalid selections.
- Preserve all page records on a page retry; sampling cannot become a complete book.
- Consolidate prompt/uncertainty schema; preserve uncertainty through cleanup.
- Remove automatic body/refrain deletion; record exclusions with evidence. Do not silently change old accepted text when upgrading cleaning rules.

Done: replaced-PDF, partial write, page retry, repeated verse, narrative “contents,” uncertainty, blank/mixed-page fixtures pass with no live calls.

### T04 — Revisions, stable anchors, additive migration

Dependencies: T01–T03. Files: `schemas.py`, `project_store.py`, models/migrations, segmenter/parser.

- Implement §4.1–4.3 and import reports; preserve PDF/checkpoints/manual plan edits/audio/history.
- Persist stable IDs/spans and explicit paragraph/page labels; source snapshots are immutable.
- Add split/merge lineage and conservative unique-match reconciliation; unknown provenance stays unknown.
- Remove import-time schema mutation after a tested migration runner exists. Test upgrading a copied old schema twice.

Done: insertion leaves unrelated targets stable; repeated text and cross-page anchors resolve correctly; unresolved legacy divergence blocks only dependent migration/work, not historical playback.

### T05 — Durable corrections and paper-note intake backend

Dependencies: T04. Files: `review/corrections.py`, models/schema, API, CLI.

- Implement preview/apply/import/undo with exact expected text and revision preconditions.
- Cover every correction kind in §4.4; unsupported operations return clear validation errors.
- Import legacy `ai_audio_fixes.json` and manual overrides conservatively; no silent loss.
- Add a named rebuild planner; it must not rerun OCR for a pronunciation fix.

Done: one local override survives unrelated resegmentation; repeated phrase affects only selected occurrence; conflict and idempotent retry tests pass; preview reports precise work scope.

### T06 — Immutable reusable speech assets and provider registry

Dependencies: T04–T05. Files: `synthesis/assets.py`, runner/providers, project configuration, API voice routes.

- Implement effective request preparation, versioned key, immutable take storage, and verified legacy import.
- Handle repeated identical requests with shared verified assets where permitted; no global cross-project cache in first version.
- Separate assembly pauses; ensure model/pace/config changes enter requests.
- Support targeted new take for a bad performance without changing source text.
- Unify exposed provider choices/defaults/capabilities across entry points. Keep real provider smoke tests optional and separate.

Done: permutations and revert require zero calls for already stored matching takes; pause/page changes require zero calls; model changes miss; corrupt assets fail verification; provider capability tests match actual request payloads.

### T07 — Local prosody and revisioned assembly/timelines

Dependencies: T06. Files: prosody, assembler, enhancer, build planner/service.

- Use real paragraph/boundary identity and explicit zero/unset pause semantics.
- Retain lossless base, derive absolute tempo, and publish build signatures/timeline/validated media together.
- Remove mastering mtime shortcut and repeated MP3 speed processing.
- Compute deterministic ordered segment timing from measured samples and declared transform mapping; test final decoded seeking tolerance.

Done: no-op rebuild performs zero provider calls and no media re-encode; pause-only assembles only; repeated speed operation is idempotent; final MP3 validates and all segments occur in the intended order.

### T08 — Candidate-bound issues, verification, and approvals

Dependencies: T05–T07. Files: `review/candidates.py`, API review routes, models, review tests.

- Implement immutable candidate URLs and explicit preconditions on mutations.
- Carry issues forward with lineage; retain both timelines and before/after audio selections.
- Add fixed-pending-check and verification evidence; decisions use effective review version.
- Separate current draft candidate from released candidate; preserve two-human approval policy.
- Publish build/candidate/current pointer atomically; reject missing media or mismatching manifests.

Done: stale-browser, carried-blocker, identical-audio/different-lineage, same-hash historical rebuild, tampering, reopened issue, and concurrent approval/blocker tests pass.

### T09 — Editor correction workspace

Dependencies: T05 and T08. Files: `ProjectPipeline.jsx`, extracted correction/recheck components, query hooks, player tests.

- Form fields: candidate, printed/PDF page, paragraph, quote/word, issue type, expected/replacement, note reference.
- Show matching PDF page/source passage; ambiguous matches require selection.
- Show correction diff and work estimate; preview containing segment plus adjacent context; apply and track build job.
- Recheck old/new selected passages and mark verified against replacement candidate.
- Preserve drafts on refetch/conflict; refresh all stage outputs only on job completion; invalidate related queries consistently.
- Use one selected audio player; show stale/failed/mapping-conflict states clearly.

Done: frontend tests cover entry → target → preview → save → incremental build → recheck; manual browser acceptance covers real PDF/audio navigation. Do not consider existing five UI tests sufficient for this workflow.

### T10 — Rollout, operational verification, documentation

Dependencies: T00–T09. Files: README, current architecture docs, migration/report scripts, scale tests.

- Pilot on copies of one small and one long existing project; compare source text, correction inventory, cached audio digests, and review history before/after migration.
- Reconcile DB/object failures, enforce retention, and demonstrate backup/restore on a copy.
- Measure rebuild time separately from OCR/TTS call count, cache verification, assembly, and encoding.
- Document stage aliases and named commands; mark older proposals as historical once superseded in code.
- Complete F15 performance work as measured and F16 deployment hardening before shared deployment. No Redis/Celery, forced alignment, chapter export, or handwriting model is required to complete the basic correction loop.

Done: checklist below passes; deliver measurements and remaining explicitly deferred items.

## 6. Mandatory acceptance matrix

Provider tests use counting doubles producing distinct valid PCM for distinct text; matching duration alone is insufficient. Media tests use short real FFmpeg fixtures. Exact timing tolerances must be documented for the selected filter/encoding path.

| Scenario | Required invariant |
| --- | --- |
| 100-segment baseline, one pronunciation change | 0 OCR requests; only changed effective speech requests synthesized; other asset digests unchanged; new candidate/approval cycle |
| One boundary gap changes | 0 OCR and 0 TTS; updated assembly/timeline |
| Printed-page label corrected | 0 OCR and 0 TTS; anchors/UI updated; audio remains reusable |
| Sentence inserted near beginning | Unchanged later asset keys reusable; only affected local paragraph planning changes; no positional retargeting |
| Reorder A/B/C to C/A/B | 0 TTS; no overwritten cache sources; correct output order |
| Two identical Sanskrit verses | Stable distinct targets; edit one occurrence; preserve both source occurrences |
| Undo and reapply correction | Old/new verified takes reused; correction history retained |
| Same request, bad generated performance | Targeted new take, other segments unchanged; selected take explicitly recorded |
| Dictionary edit | Replan; synthesize only effective request differences |
| Model or explicit pace changes | Requests reflect change; stale assets never falsely reported current |
| Source correction overlaps accepted pronunciation edit | Unique safe rebase or explicit conflict; never discard silently |
| Repeated rebuild/no-op save | No OCR/TTS/re-encode; revision/correction idempotency |
| New PDF at same filename | Old checkpoints do not pass source binding |
| Page retry / failed page resume | Other pages and accepted corrections preserved; complete coverage required |
| Unknown printed page or paragraph | Search/context selection; no guessed application |
| Error/uncertainty marker | Visible unresolved issue; no silent cleaner omission or synthesis |
| Two editor saves from same base | One conditional success, one 409/conflict; losing draft remains recoverable |
| Two workers / expired worker returns | One valid owner; obsolete owner cannot publish or finish successor |
| Worker crashes after object rename before DB commit | Last valid pointer remains; orphan reported/reusable safely |
| Disk full / backup failure / invalid restore | No lost active revision/history; clear failure |
| A displayed, B generated before comment submit | Explicit A-bound submission or conflict; never attach to B implicitly |
| Blocking issue in A remains unresolved | Visible/blocking in B until verified/dismissed with evidence |
| Reopened issue / changes requested after approval | Release eligibility recalculated under current review version |
| Approved A exists; build B | A history/release preserved; B starts its own review cycle |
| Named old master exists, new chunks complete | Old master not served as current B |
| Repeated speed 1.10 request | Absolute target speed; no compounding or repeated lossy source encoding |
| Source/plan/meta changes without speech change | Accurate new lineage and packaging behavior; reuse audio without transferring inappropriate approvals |
| Unauthorized project/candidate/correction access | Existing assignment policy enforced including new media/source routes |
| Large fixture | Bounded queued tasks/player loads; measured writes/memory; no unsupported speed promises |

## 7. Migration and fallback rules

1. Inventory and back up DB plus projects consistently. Operate on a copy for the first migration; never use `reset_db.py` for this work.
2. Produce a read-only report: conflicting root/stage aliases, missing manifests, manual phonetics differences, unbound OCR checkpoints, candidate hashes, unknown source anchors, and active jobs.
3. Add schema/tables first. Import existing material as immutable legacy revisions/assets; never infer unknown model settings or invent approvals/source positions.
4. Choose one writer version per migrated project. Legacy paths are exports, not alternate editing surfaces. If both aliases differ, require explicit selection in an import report/CLI/UI before dependent processing; retain both originals.
5. Cache adoption verifies bytes and records provenance. Fully matching known request settings may reuse immediately; unknown settings require explicit adoption or regeneration. Do not trigger a paid full-book rebuild automatically during migration.
6. Preserve existing approved candidate bytes and historical decisions. If their source/plan lineage is unknown, label it; do not retroactively claim stronger verification. New release actions follow the new gates.
7. Record migration IDs and reversible mappings. Application fallback must be read-only for migrated projects unless it understands new revisions. Do not downgrade/delete new corrections to make old code write again.
8. No automatic GC during migration or early rollout. Keep objects referenced by legacy candidates, correction history, and releases. Verify a complete restore before changing retention.

## 8. Instructions to the implementing model

Read this file, relevant source functions, and current tests before each ticket. Treat the observed current code as evidence; older documents are context. Implement T00 through T10 in order, with small reviewable changes and tests per ticket. Do not undertake a wholesale framework rewrite. Preserve all existing user files and untracked experiments unless a ticket explicitly migrates them with a report.

Keep fixes scoped to the application paths users actually run (`run.py` → `pipeline_v3.py`, API → shared service). Do not implement only in the alternate `synthesis/speech` stack. Retain original source spelling in source revisions; respelling belongs in speech corrections. Never resolve an ambiguous handwritten note automatically.

Run relevant targeted tests after each change, then the full backend/frontend suites before handoff. Add real short-media validation where mocks currently bypass it. Paid/live synthesis is not necessary for regression tests. If provider behavior needs verification, record that separately and require an explicitly configured test budget rather than calling a real book pipeline.

For each ticket report: files changed, behaviors corrected, tests/results, migrations, compatibility considerations, and remaining conflicts/deferred work. Do not mark this project complete merely because tests pass: demonstrate the complete paper-note → precise correction → reused audio → replacement candidate → checker verification workflow on a migrated fixture.
