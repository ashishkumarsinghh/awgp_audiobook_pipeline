# AWGP Audiobook AI Pipeline: In-Depth Research & Solution Analysis

This document provides a comprehensive analysis of the pain points in converting AWGP PDF books to high-quality audiobooks. For each problem, we explore multiple potential solutions, detailing the **Pros** and **Cons** to help determine the best architectural path forward.

---

## 1. Problem: Bad Quality of OCR (PDF to Text Extraction)
Spiritual texts often have complex layouts (columns, borders, headers) and Devanagari script features (matras, half-letters) that standard OCR engines misinterpret.

### Option A: Tesseract OCR (Current Standard)
*   **Pros:** Free, open-source, easy to run locally, widely supported.
*   **Cons:** Very poor at complex layouts. High error rate on Hindi matras (often missing an anusvara or swapping similar-looking characters like 'ब' and 'व').

### Option B: Google Cloud Vision API
*   **Pros:** Industry gold-standard for Devanagari and Sanskrit. Excellent layout parsing and extremely high accuracy.
*   **Cons:** Paid service (first 1000 pages/month are free, then ~$1.50 per 1000 pages). Requires internet and API keys.

### Option C: Surya OCR (Deep Learning based)
*   **Pros:** Open-source, free, state-of-the-art for document layout analysis. Explicitly designed to handle multi-lingual documents better than Tesseract.
*   **Cons:** Requires a decent local machine (preferably with a GPU) to run fast. Setup is more complex than Tesseract.

### Option D: Bhashini / AI4Bharat Indic OCR
*   **Pros:** Government-backed initiative specifically trained on vast datasets of Indian languages. Exceptional accuracy for pure Hindi/Sanskrit text. Free to use via APIs.
*   **Cons:** API rate limits may apply. Integration requires interacting with their specific API structures.

> **Recommendation:** Use **Surya OCR** if processing locally on a good machine, or **Google Cloud Vision** if budget allows for near-perfect baseline extraction.

---

## 2. Problem: The "Match" Bottleneck & Nuanced Shantikunj Rules
The human effort required to compare the PDF against OCR text and apply Shantikunj-specific grammar rules (Chandrabindu, standardizing anusvaras) is immense.

### Option A: Manual Editing in Word/Notepad
*   **Pros:** Zero development cost.
*   **Cons:** Extreme human fatigue. High cognitive load switching between PDF viewer and text editor. Slowest method.

### Option B: Rule-Based Pre-processing + Split-Screen Web UI
Pass text through a Python Regex script to fix 80% of common Shantikunj rules *before* a human sees it. Then present it in a Streamlit app with the PDF image on the left and text on the right.
*   **Pros:** Massive time savings. Deterministic (Regex rules always behave exactly the same way). UI prevents "window switching" fatigue. Cheap and easy to build.
*   **Cons:** Requires time to initially catalog all Shantikunj rules into Python Regex patterns.

### Option C: LLM-Based Auto-Correction (e.g., GPT-4o / Gemini)
Prompt an LLM: "Fix OCR errors in this text according to these Shantikunj grammatical rules."
*   **Pros:** Can fix contextual errors that Regex misses (e.g., understanding a mangled word based on the sentence meaning).
*   **Cons:** **High Risk of Hallucination.** The LLM might rewrite the sentence, changing revered spiritual text. Paid API costs.

> **Recommendation:** **Option B** (Regex + Split-Screen UI). It is deterministic, safe for spiritual texts (no hallucinations), and solves the UX bottleneck.

---

## 3. Problem: TTS WPM Changes & Monotonous Delivery
TTS models often start at a normal speed and slowly increase WPM towards the end of a long text because they are struggling with a large context window. They also sound "flat".

### Option A: Whole-Document Processing (Standard Approach)
Feeding whole paragraphs or pages to the TTS engine.
*   **Pros:** Easy to code (one API call).
*   **Cons:** Causes the "WPM creeping" bug. Results in monotonous, rushed audio.

### Option B: Sentence-Level Chunking & Stitching
Break the text by full stops (`।` or `.`). Send one sentence at a time to the TTS, then stitch the resulting `.wav` files together using `ffmpeg`.
*   **Pros:** **Completely eliminates the WPM increase bug.** The model's context resets every sentence, guaranteeing stable pacing.
*   **Cons:** Requires managing multiple audio files and stitching them, slightly increasing processing time.

### Option C: SSML Tagging (Speech Synthesis Markup Language)
Wrap text in XML tags that explicitly tell the TTS how to behave (e.g., `<break time="500ms"/>` for commas, `<prosody rate="medium">`).
*   **Pros:** Cures the "flatness" problem. Allows you to add breath pauses, emphasize words, and control exactly how the text flows.
*   **Cons:** Requires a pre-processing step to inject these tags into the raw text.

### Option D: Voice Cloning / Custom VITS Training
Train a custom open-source AI voice (like VITS) on a human AWGP narrator.
*   **Pros:** Perfect tone, emotion, and Shantikunj-approved pronunciation. No recurring API costs once trained.
*   **Cons:** Highly technical, requires heavy GPU compute, and needs hours of clean, isolated human audio to train properly.

> **Recommendation:** Combine **Option B (Chunking)** and **Option C (SSML)** using a free tool like **Edge-TTS** (Microsoft Neural voices).

---

## 4. Problem: Sanskrit Shlokas Incorrectly Pronounced
Standard Hindi TTS models do not know the rules of classical Sanskrit chanting or specific Sandhi pronunciation.

### Option A: Forcing Hindi TTS to read Sanskrit
*   **Pros:** No extra work.
*   **Cons:** Disrespectful to the text; highly inaccurate pronunciation (e.g., dropping terminal 'a' sounds, incorrect visarga/anusvara pronunciation).

### Option B: Phonetic Transliteration
Rewrite the Shloka in a way that "tricks" the Hindi TTS into pronouncing it correctly (e.g., spelling out silent sounds).
*   **Pros:** Works with any basic TTS engine.
*   **Cons:** Incredibly tedious to write phonetic rules for every Shloka.

### Option C: Dedicated Sanskrit TTS Routing
Detect Shlokas in the text (e.g., lines ending in `॥`) and route *only* those lines to a dedicated Sanskrit model (e.g., Bhashini `sa-IN` or Azure `sa-IN` voices).
*   **Pros:** Authentic, accurate pronunciation. Preserves the sanctity of the mantras.
*   **Cons:** The voice of the narrator will briefly change during the Shloka. (This can be mitigated by choosing a Sanskrit voice that sounds similar to the Hindi voice, or treating it as a stylistic choice—like a distinct "chanting" voice).

> **Recommendation:** **Option C** (Dedicated Routing). The slight voice change is vastly preferable to incorrect mantra pronunciation.

---

## 5. Problem: QA & Bad Audio Conversion Mistakes
Currently, discovering that a TTS model skipped a word or hallucinated requires a human to listen to the entire generated audiobook.

### Option A: Human QA Listening
*   **Pros:** Catches emotional nuances and pacing issues.
*   **Cons:** Extremely time-consuming (1 hour of audio = 1 hour of QA). Doesn't scale.

### Option B: Reverse ASR + WER Calculation
Run the generated audio through a fast Speech-to-Text model (like **faster-whisper**). Compare this transcript to the master text. Calculate the Word Error Rate (WER).
*   **Pros:** Fully automated. If WER is < 1%, the audio is mathematically proven to be accurate. Humans only need to review the specific 5-second chunks where the WER spiked.
*   **Cons:** Whisper might occasionally mistranscribe perfectly good audio, creating false positives.

> **Recommendation:** **Option B**. Automate the tedious part of QA so humans only audit flagged anomalies.
