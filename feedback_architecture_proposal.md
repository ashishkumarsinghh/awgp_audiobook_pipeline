# Architecture & Design Proposals: Efficient Feedback & Editing

Based on the feedback workflow (users report issues via handwritten notes specifying Page & Paragraph) and the current pipeline architecture (`01_ocr_raw.txt` -> `segments.json` -> `phonetics.json` -> `audio_chunks` -> `mastered.mp3`), here is an analysis of the current pain points and a proposed architectural design to make editing rapid, robust, and efficient.

## Current Vulnerabilities
1. **Destructive Overwrites**: If an editor manually fixes a typo in `04_phonetics.json`, re-running Stage 1 or 2 (e.g., if OCR text is updated) will completely overwrite and erase the manual fix.
2. **Locatability**: Finding the exact chunk for "Page 6, Paragraph 2" is very tedious because `segments.json` uses generic sequential IDs (`chunk_0045`) without retaining the original page numbers from the OCR text.
3. **Pipeline Fragility**: A structural change (like adding a missing full stop in the OCR text) splits one chunk into two. This shifts the sequential IDs of *all subsequent chunks*, which historically broke the audio cache. (Note: We mitigated the audio cache part with the recent fingerprinting patch, but the data flow is still fragile for manual JSON edits).

---

## Proposed Architectural Solutions

### 1. Embed Source Metadata in Chunks (Stage 1 Enhancement)
**The Concept**: The OCR text often contains page footers (e.g., `[ 6 ]` or `६ ]`). The Text Segmenter (`Stage 1`) should be enhanced to detect these page boundaries and track paragraph breaks.
**Implementation**: Inject this metadata directly into the chunk schema.
```json
{
  "id": "chunk_0045",
  "page": 6,
  "paragraph": 2,
  "source_text": "...",
  "segment_type": "prose",
  "pause_after_ms": 600
}
```
**Why it helps**: When a reviewer says "Page 6, Para 2 has a typo", an editor (or a script) can instantly query and find `chunk_0045`.

### 2. Stateless Corrections Configuration (`project_corrections.yaml`)
**The Concept**: Stop editing the intermediate JSON files (`segments.json`, `phonetics.json`). Instead, create a single `project_corrections.yaml` file at the root of the project where editors record all human feedback.
**Implementation**:
```yaml
corrections:
  # 1. OCR Typo Fix (Applied during Stage 1)
  - page: 6
    paragraph: 2
    type: text_replace
    find: "प्रोताहन"
    replace: "प्रोत्साहन"
    
  # 2. TTS Mispronunciation (Applied during Stage 2)
  - page: 12
    type: pronunciation
    find: "बी० ए०"
    replace: "बी ए"
    
  # 3. Prosody Adjustment (Applied during Stage 2)
  - page: 20
    paragraph: 4
    type: prosody
    pause_after_ms: 1200
```
**Why it helps**: The pipeline becomes fully idempotent (re-runnable without side effects). You can delete all intermediate files, run `python run.py <book> all`, and the pipeline will perfectly recreate the book with all human corrections applied. 

### 3. Build a Quick-Edit CLI Tool
**The Concept**: Manually writing YAML can be tedious. We can build an interactive CLI tool (`python edit.py`).
**Implementation**:
```bash
$ python edit.py --book NAE_JIVAN --page 6 --para 2

Found Chunk: "नाटक के पात्रों का यह सामान्य अनुभव है कि..."
What would you like to fix?
1. Text typo
2. Pronunciation
3. Pause duration
> 1
Find: प्रोताहन
Replace: प्रोत्साहन

Fix saved to project_corrections.yaml! Run pipeline to apply.
```
**Why it helps**: It bridges the gap between the handwritten feedback and the codebase, allowing non-technical editors to quickly insert fixes.

### 4. Leverage "Smart Caching" for Instant Rebuilds
**The Concept**: Because of the fingerprinting update we just pushed, the TTS engine no longer cares about `chunk_id`. It only hashes the actual text and pause duration.
**Execution Flow**:
1. Editor logs a fix on Page 6.
2. Editor runs `python run.py <book> all`.
3. **Stage 1 & 2** run instantly (takes ~1 second) and apply the YAML corrections.
4. **Stage 3 (Audio)** hashes all chunks. 99% of chunks match the existing audio cache and are skipped. **Only the single corrected chunk on Page 6 is sent to the TTS API** (takes ~2 seconds).
5. **Stage 4** stitches the master file back together (takes ~10 seconds).
**Why it helps**: Fixing a single typo and getting a brand new Master MP3 takes less than 15 seconds end-to-end, with zero risk of breaking unaffected chapters.

---
## Summary of Next Steps
If you agree with this direction, we can implement it in the following phases:
1. **Phase 1**: Update the segmenter logic in Stage 1 to track and embed `page` and `paragraph` metadata into `segments.json`.
2. **Phase 2**: Create the `project_corrections.yaml` parser and inject its logic into Stage 1 (Text Replacements) and Stage 2 (Pronunciations & Prosody).
3. **Phase 3**: Create the interactive `edit.py` CLI tool for fast data entry.
