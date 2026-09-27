# AWGP Audiobook Pipeline

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
