import os
import json
import argparse
import asyncio
import re
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from dotenv import load_dotenv

load_dotenv()

import fitz
from src.core.artifacts import atomic_write, write_json, read_segments
from src.synthesis.runner import synthesize_segments, as_segment, load_manifest, is_current

from src.core.types import NarrationProfile, SpeechSegment
from src.normalize.segmenter import SemanticSegmenter
from src.normalize.text_cleaner import clean_book_headers_and_metadata
from src.normalize.pronunciation import PronunciationDictionary
from src.synthesis.prosody import ProsodyPlanner
from src.synthesis.providers import EdgeTTSProvider, GeminiTTSProvider, GoogleCloudTTSProvider, AzureSpeechProvider, GoogleAIStudioTTSProvider, SarvamTTSProvider
from src.synthesis.assembler import AudioAssembler
from src.synthesis.audio.enhancer import AudioEnhancer


def normalize_cli_path(p: Optional[str]) -> Optional[str]:
    r"""Normalizes paths, converting Windows drive formats (e.g. C:\...) when running in WSL/Linux."""
    if not p:
        return p
    val = p.strip()
    if os.name != 'nt' and re.match(r'^[a-zA-Z]:[\\/]', val):
        drive = val[0].lower()
        rest = val[2:].replace('\\', '/')
        val = f"/mnt/{drive}{rest}"
    return val


def get_latest_file(*paths: Optional[str]) -> Optional[str]:
    """Returns the path with the latest modification time among existing files."""
    valid = [p for p in paths if p and os.path.isfile(p)]
    if not valid:
        return None
    return max(valid, key=os.path.getmtime)


class ProjectManager:
    def __init__(
        self,
        project_dir: str,
        tts_provider: Optional[str] = None,
        tts_voice: Optional[str] = None,
        book_name: Optional[str] = None
    ):
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.book_name = book_name or os.path.basename(os.path.normpath(self.project_dir))

        # Canonical project-level files
        self.pdf_file = os.path.join(self.project_dir, '00_scanned.pdf')
        self.raw_file = os.path.join(self.project_dir, '01_ocr_raw.txt')
        self.clean_file = os.path.join(self.project_dir, '02_text_cleaned.txt')
        self.segments_file = os.path.join(self.project_dir, '03_segments.json')
        self.phonetics_file = os.path.join(self.project_dir, '04_phonetics.json')
        self.audio_dir = os.path.join(self.project_dir, '05_audio_chunks')
        self.master_file = os.path.join(self.project_dir, '06_mastered.mp3')
        self.artifacts_dir = os.path.join(self.project_dir, 'artifacts')

        # Dedicated stage subfolders where inputs and outputs are isolated and edited
        self.stage0_dir = os.path.join(self.project_dir, '00_ocr')
        self.stage1_dir = os.path.join(self.project_dir, '01_segments')
        self.stage2_dir = os.path.join(self.project_dir, '02_phonetics')
        self.stage3_dir = os.path.join(self.project_dir, '03_audio')
        self.stage4_dir = os.path.join(self.project_dir, '04_master')
        self.named_master_file = os.path.join(self.stage4_dir, f"{self.book_name}.mp3")
        self.stage4_master_file = os.path.join(self.stage4_dir, 'mastered.mp3')
        self.ocr_checkpoints_dir = os.path.join(self.stage0_dir, 'checkpoints')

        for d in [
            self.audio_dir, self.artifacts_dir, self.stage0_dir,
            self.stage1_dir, self.stage2_dir, self.stage3_dir,
            self.stage4_dir, self.ocr_checkpoints_dir
        ]:
            os.makedirs(d, exist_ok=True)

        self._sync_audio_folders()

        self.profile = NarrationProfile()
        self.segmenter = SemanticSegmenter(self.profile)
        pronunciation_file = os.environ.get("PRONUNCIATION_FILE")
        self.pronunciation = PronunciationDictionary(pronunciation_file)
        self.prosody = ProsodyPlanner(self.profile)
        self.tts_provider = (tts_provider or os.environ.get('TTS_PROVIDER', 'edge')).lower()
        self.tts = self._get_tts_provider(tts_voice)

    def _sync_audio_folders(self):
        """Keep 05_audio_chunks and 03_audio in sync."""
        if os.path.exists(self.audio_dir) and os.path.exists(self.stage3_dir):
            for f in os.listdir(self.audio_dir):
                src = os.path.join(self.audio_dir, f)
                dest = os.path.join(self.stage3_dir, f)
                if os.path.isfile(src):
                    if not os.path.exists(dest) or os.path.getmtime(src) > os.path.getmtime(dest):
                        try:
                            shutil.copyfile(src, dest)
                        except Exception:
                            pass

    def _get_tts_provider(self, voice: Optional[str] = None):
        if self.tts_provider in {'sarvam', 'sarvamai', 'sarvam-ai'}:
            voice = voice or os.environ.get('TTS_VOICE') or 'shubh'
            return SarvamTTSProvider(voice)
        if self.tts_provider in {'studio', 'gemini-studio', 'google-studio'}:
            voice = voice or os.environ.get('TTS_VOICE') or 'Kore'
            return GoogleAIStudioTTSProvider(voice)
        if self.tts_provider in {'google', 'gcloud'}:
            voice = voice or os.environ.get('TTS_VOICE') or 'hi-IN-Neural2-B'
            return GoogleCloudTTSProvider(voice)
        if self.tts_provider == 'gemini':
            voice = voice or os.environ.get('TTS_VOICE') or 'hi-IN-Wavenet-A'
            return GoogleCloudTTSProvider(voice)
        voice = voice or os.environ.get('TTS_VOICE') or self.profile.voice
        if self.tts_provider == 'azure':
            return AzureSpeechProvider(voice)
        if self.tts_provider == 'edge':
            return EdgeTTSProvider(voice)
        raise ValueError(f'Unsupported TTS provider: {self.tts_provider}')

    def save_timestamped_artifact(self, stage_label: str, file_type: str, source_path: str, tag: str = "cli") -> Optional[str]:
        """Saves a timestamped, book-tagged version of an artifact to artifacts/ folder."""
        if not os.path.exists(source_path):
            return None
        os.makedirs(self.artifacts_dir, exist_ok=True)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_book = re.sub(r'[^a-zA-Z0-9_-]', '_', self.book_name)
        clean_stage = re.sub(r'[^a-zA-Z0-9_-]', '_', stage_label)
        clean_tag = re.sub(r'[^a-zA-Z0-9_-]', '_', tag)
        artifact_filename = f"{clean_book}_{clean_stage}_{clean_tag}_{now_str}.{file_type}"
        dest_path = os.path.join(self.artifacts_dir, artifact_filename)
        shutil.copyfile(source_path, dest_path)
        return dest_path

    def resolve_metadata(self, custom_metadata: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Resolves comprehensive ID3 metadata for the audiobook from project artifacts."""
        voice_name = getattr(self.tts, 'voice', 'hi-IN-MadhurNeural') if hasattr(self, 'tts') and self.tts else 'hi-IN-MadhurNeural'
        meta = {
            "title": "",
            "artist": "पं. श्रीराम शर्मा आचार्य (Pt. Shriram Sharma Acharya)",
            "album_artist": "अखिल विश्व गायत्री परिवार (AWGP)",
            "album": "",
            "publisher": "युग निर्माण योजना, शांतिकुंज हरिद्वार (AWGP)",
            "genre": "Audiobook",
            "date": "",
            "track": "1/1",
            "comment": f"AWGP Audiobooks - Voice: {voice_name}, AWGP Audiobook Pipeline",
        }

        # 1. Year extraction from book_name or PDF
        year_match = re.search(r'(19\d{2}|20\d{2})', self.book_name)
        if year_match:
            meta["date"] = year_match.group(1)

        # 2. Heading / Title extraction
        heading_text = ""
        s1_file = os.path.join(self.stage1_dir, "segments.json")
        if not os.path.isfile(s1_file):
            s1_file = self.segments_file
        if os.path.isfile(s1_file):
            try:
                segs = read_segments(s1_file)
                for s in segs:
                    if s.get("segment_type") == "heading" and s.get("source_text"):
                        heading_text = s["source_text"].strip()
                        break
            except Exception:
                pass

        if not heading_text:
            s0_clean = os.path.join(self.stage0_dir, "text_cleaned.txt")
            if not os.path.isfile(s0_clean):
                s0_clean = self.clean_file
            if os.path.isfile(s0_clean):
                try:
                    with open(s0_clean, "r", encoding="utf-8") as f:
                        content = f.read(5000)
                        h_match = re.search(r'<heading>(.*?)</heading>', content, re.DOTALL)
                        if h_match:
                            heading_text = h_match.group(1).strip()
                except Exception:
                    pass

        # 3. Derive Album / Book Title
        clean_name = re.sub(r'^(HINR\d+_|GUJR\d+_|ENGR\d+_)', '', self.book_name)
        clean_name = re.sub(r'_(Re\d{4}|\d{4})$', '', clean_name)
        album_name = clean_name.replace('_', ' ').strip().title()

        meta["title"] = heading_text if heading_text else (album_name if album_name else self.book_name)
        meta["album"] = album_name if album_name else meta["title"]

        if custom_metadata:
            for k, v in custom_metadata.items():
                if v:
                    meta[k] = str(v).strip()

        return meta

    def invalidate_after(self, stage: str):
        """Remove derived active artifacts; keep immutable history in artifacts/ and reusable audio."""
        downstream = {
            "raw": [
                self.segments_file, self.phonetics_file, self.master_file,
                os.path.join(self.stage1_dir, 'segments.json'),
                os.path.join(self.stage2_dir, 'phonetics.json'),
                os.path.join(self.stage4_dir, 'mastered.mp3'),
            ],
            "clean": [
                self.segments_file, self.phonetics_file, self.master_file,
                os.path.join(self.stage1_dir, 'segments.json'),
                os.path.join(self.stage2_dir, 'phonetics.json'),
                os.path.join(self.stage4_dir, 'mastered.mp3'),
            ],
            "segments": [
                self.phonetics_file, self.master_file,
                os.path.join(self.stage2_dir, 'phonetics.json'),
                os.path.join(self.stage4_dir, 'mastered.mp3'),
            ],
            "phonetics": [
                self.master_file,
                os.path.join(self.stage4_dir, 'mastered.mp3'),
            ],
        }
        for path in downstream.get(stage, []):
            if os.path.isfile(path):
                base = os.path.splitext(os.path.basename(path))[0]
                ext = os.path.splitext(path)[1].lstrip('.')
                try:
                    self.save_timestamped_artifact(f"backup_{base}", ext, path, tag="invalidated")
                except Exception:
                    pass
                os.remove(path)

    def _locate_pdf(self, input_pdf: Optional[str] = None) -> str:
        if input_pdf and os.path.exists(input_pdf):
            return input_pdf
        # Check in stage subfolder
        for name in os.listdir(self.stage0_dir):
            if name.lower().endswith(".pdf"):
                return os.path.join(self.stage0_dir, name)
        # Check canonical 00_scanned.pdf
        if os.path.exists(self.pdf_file):
            return self.pdf_file
        # Check root book pdf
        root_book_pdf = f"{self.book_name}.pdf"
        if os.path.isfile(root_book_pdf):
            return os.path.abspath(root_book_pdf)
        return self.pdf_file

    def run_stage_1_ocr(
        self,
        input_pdf: Optional[str] = None,
        output_file: Optional[str] = None,
        max_pages: Optional[int] = None,
        pages_to_process: Optional[List[int]] = None
    ) -> str:
        """Stage 0 (OCR): Reads PDF, runs OCR with checkpoints, saves to 00_ocr/ocr_raw.txt."""
        from src.extract.ocr_engine import extract_text_from_pdf
        target_pdf = self._locate_pdf(input_pdf)
        if not os.path.exists(target_pdf):
            raise FileNotFoundError(f"PDF {target_pdf} not found. Provide a PDF or place it in {self.stage0_dir}/.")

        if os.path.abspath(target_pdf) != os.path.abspath(self.pdf_file) and not os.path.exists(self.pdf_file):
            try:
                shutil.copyfile(target_pdf, self.pdf_file)
            except Exception:
                pass

        stage0_raw = os.path.join(self.stage0_dir, 'ocr_raw.txt')
        target_out = output_file or stage0_raw

        text = extract_text_from_pdf(
            target_pdf,
            max_pages=max_pages,
            checkpoint_dir=self.ocr_checkpoints_dir,
            book_name=self.book_name,
            pages_to_process=pages_to_process
        )
        if not text.strip():
            raise RuntimeError("OCR returned no text. Check the PDF and OCR configuration.")

        atomic_write(target_out, text)
        if target_out != self.raw_file:
            atomic_write(self.raw_file, text)
        if target_out != stage0_raw:
            atomic_write(stage0_raw, text)

        cleaned_text = clean_book_headers_and_metadata(text, book_title=self.book_name)
        stage0_cleaned = os.path.join(self.stage0_dir, 'text_cleaned.txt')
        if cleaned_text:
            atomic_write(stage0_cleaned, cleaned_text)
            if self.clean_file != stage0_cleaned:
                atomic_write(self.clean_file, cleaned_text)
            self.save_timestamped_artifact("01_text_cleaned", "txt", stage0_cleaned)

        if not input_pdf:
            self.invalidate_after("raw")

        self.save_timestamped_artifact("00_ocr_raw", "txt", target_out)
        print(f"[Stage 0: OCR] Complete: Saved raw to {target_out}, cleaned to {stage0_cleaned}")
        print(f"  -> Edits can be made directly in: {stage0_cleaned} (or {stage0_raw})")
        return target_out

    run_stage_0_ocr = run_stage_1_ocr

    def run_stage_1_segmentation(self, input_text_file: Optional[str] = None, output_file: Optional[str] = None, force: bool = False) -> str:
        """Stage 1 (Segmentation): Reads text from 00_ocr/ (or edited input), segments it, saves to 01_segments/segments.json."""
        s0_cleaned = os.path.join(self.stage0_dir, 'text_cleaned.txt')
        s0_raw = os.path.join(self.stage0_dir, 'ocr_raw.txt')

        # Pick the latest edited text
        if input_text_file:
            target_txt = input_text_file
        else:
            # Cleaned OCR is authoritative. Do not let a same-timestamp raw
            # alias win and bypass header/footer removal.
            target_txt = next(
                (path for path in (s0_cleaned, self.clean_file) if path and os.path.isfile(path)),
                get_latest_file(s0_raw, self.raw_file),
            )
        if not target_txt or not os.path.isfile(target_txt):
            raise FileNotFoundError(f"No input text found in {self.stage0_dir} or {self.project_dir}. Run Stage 0 (OCR) first.")

        stage1_out = os.path.join(self.stage1_dir, 'segments.json')
        target_out = output_file or stage1_out

        if not force and os.path.isfile(target_out) and os.path.getmtime(target_out) >= os.path.getmtime(target_txt):
            print(f"[Stage 1: Segmentation] Skipped: {target_out} is already up-to-date with {target_txt}.")
            return target_out

        print(f"[Stage 1: Segmentation] Reading source text from: {target_txt}")
        with open(target_txt, 'r', encoding='utf-8') as f:
            text = f.read()

        segments = self.segmenter.segment_text(text)
        if not segments:
            raise ValueError('No narration text found. Review OCR before segmentation.')

        data = [
            {
                "id": f"chunk_{i+1:04d}",
                "source_text": seg.source_text,
                "segment_type": seg.segment_type,
                "pause_after_ms": seg.pause_after_ms
            }
            for i, seg in enumerate(segments)
        ]



        write_json(target_out, data)
        if target_out != self.segments_file:
            write_json(self.segments_file, data)
        if target_out != stage1_out:
            write_json(stage1_out, data)

        if not input_text_file:
            self.invalidate_after('segments')

        self.save_timestamped_artifact("02_segments", "json", target_out)
        print(f"[Stage 1: Segmentation] Complete: {len(data)} segments saved to {target_out}")
        print(f"  -> Edits can be made directly in: {stage1_out}")
        return target_out

    def run_stage_2_phonetics(self, input_segments_file: Optional[str] = None, output_file: Optional[str] = None, force: bool = False) -> str:
        """Stage 2 (Phonetics): Reads segments from 01_segments/ (or edited input), applies prosody, saves to 02_phonetics/phonetics.json."""
        s1_seg = os.path.join(self.stage1_dir, 'segments.json')

        # Pick the latest edited segments file
        target_in = input_segments_file or get_latest_file(s1_seg, self.segments_file)
        if not target_in or not os.path.isfile(target_in):
            raise FileNotFoundError(f"Segments file not found in {self.stage1_dir} or {self.project_dir}. Run Stage 1 (Segmentation) first.")

        stage2_out = os.path.join(self.stage2_dir, 'phonetics.json')
        target_out = output_file or stage2_out

        if not force and os.path.isfile(target_out) and os.path.getmtime(target_out) >= os.path.getmtime(target_in):
            print(f"[Stage 2: Phonetics] Skipped: {target_out} is already up-to-date with {target_in}.")
            return target_out

        print(f"[Stage 2: Phonetics] Reading segments from: {target_in}")
        data = read_segments(target_in)

        segments = []
        for item in data:
            seg = SpeechSegment(
                source_text=item.get("source_text", ""),
                normalized_text=item.get("source_text", ""),
                pronunciation_text=item.get("source_text", ""),
                segment_type=item.get("segment_type", "prose"),
                pause_after_ms=item.get("pause_after_ms", 0)
            )
            seg.pronunciation_text = self.pronunciation.apply(seg.source_text, context=seg.segment_type)
            segments.append(seg)

        segments = self.prosody.apply_prosody(segments)

        out_data = [
            {
                "id": data[i]["id"],
                "source_text": seg.source_text,
                "segment_type": seg.segment_type,
                "pronunciation_text": seg.pronunciation_text,
                "rate": seg.rate,
                "pitch": seg.pitch,
                "volume": seg.volume,
                "pause_before_ms": seg.pause_before_ms,
                "pause_after_ms": seg.pause_after_ms
            }
            for i, seg in enumerate(segments)
        ]



        write_json(target_out, out_data)
        if target_out != self.phonetics_file:
            write_json(self.phonetics_file, out_data)
        if target_out != stage2_out:
            write_json(stage2_out, out_data)

        if not input_segments_file:
            self.invalidate_after('phonetics')

        self.save_timestamped_artifact("03_phonetics", "json", target_out)
        print(f"[Stage 2: Phonetics] Complete: {len(out_data)} phonetic segments saved to {target_out}")
        print(f"  -> Edits can be made directly in: {stage2_out}")
        return target_out

    def run_stage_3_audio(self, input_phonetics_file: Optional[str] = None, audio_dir: Optional[str] = None) -> str:
        """Stage 3 (Audio): Reads phonetics from 02_phonetics/ (or edited input), synthesizes into 03_audio/."""
        s2_ph = os.path.join(self.stage2_dir, 'phonetics.json')

        # Pick the latest edited phonetics file
        target_in = input_phonetics_file or get_latest_file(s2_ph, self.phonetics_file)
        if not target_in or not os.path.isfile(target_in):
            raise FileNotFoundError(f"Phonetics file not found in {self.stage2_dir} or {self.project_dir}. Run Stage 2 (Phonetics) first.")

        # Canonical audio directory used for synthesis
        target_audio_dir = audio_dir or self.audio_dir
        os.makedirs(target_audio_dir, exist_ok=True)
        os.makedirs(self.stage3_dir, exist_ok=True)

        print(f"[Stage 3: Audio] Reading phonetics from: {target_in}")
        print(f"[Stage 3: Audio] Synthesizing into: {target_audio_dir} (Provider: {self.tts_provider}, Voice: {self.tts.voice})")
        data = read_segments(target_in)

        if not input_phonetics_file:
            self.invalidate_after("phonetics")

        asyncio.run(synthesize_segments(data, target_audio_dir, self.tts, self.tts_provider))

        # Mirror chunks and manifest to 03_audio
        self._sync_audio_folders()

        manifest_path = os.path.join(target_audio_dir, "manifest.json")
        if os.path.exists(manifest_path):
            self.save_timestamped_artifact("04_audio_manifest", "json", manifest_path)

        print(f"[Stage 3: Audio] Complete: Verified {len(data)} audio chunks in {target_audio_dir}")
        return target_audio_dir

    def run_stage_4_mastering(
        self,
        input_phonetics_file: Optional[str] = None,
        audio_dir: Optional[str] = None,
        output_file: Optional[str] = None,
        speed: Optional[float] = None,
        metadata: Optional[Dict[str, str]] = None,
        eq_profile: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """Stage 4 (Mastering): Validates chunks from 03_audio/, assembles studio-grade master to 04_master/<book_name>.mp3."""
        s2_ph = os.path.join(self.stage2_dir, 'phonetics.json')

        target_in = input_phonetics_file or get_latest_file(s2_ph, self.phonetics_file)
        if not target_in or not os.path.isfile(target_in):
            raise FileNotFoundError(f"Phonetics file not found. Run Stage 2 first.")

        # Determine audio directory (favor audio_dir with manifest)
        target_audio_dir = audio_dir
        if not target_audio_dir:
            if os.path.isfile(os.path.join(self.audio_dir, 'manifest.json')):
                target_audio_dir = self.audio_dir
            elif os.path.isfile(os.path.join(self.stage3_dir, 'manifest.json')):
                target_audio_dir = self.stage3_dir
            else:
                target_audio_dir = self.audio_dir

        target_out = output_file or self.named_master_file

        manifest_path = os.path.join(target_audio_dir, "manifest.json")
        if not force and os.path.isfile(target_out):
            if os.path.getmtime(target_out) >= os.path.getmtime(target_in):
                if os.path.isfile(manifest_path) and os.path.getmtime(target_out) >= os.path.getmtime(manifest_path):
                    print(f"[Stage 4: Mastering] Skipped: {target_out} is already up-to-date.")
                    return target_out
                elif not os.path.isfile(manifest_path):
                    print(f"[Stage 4: Mastering] Skipped: {target_out} is up-to-date.")
                    return target_out

        target_speed = speed if speed is not None else getattr(self.profile, 'mastering_speed', 1.15)
        target_eq = eq_profile or getattr(self.profile, 'eq_profile', 'smooth')
        print(f"[Stage 4: Mastering] Assembling chunks from: {target_audio_dir} (Tempo: {target_speed:.2f}x, EQ: {target_eq})")
        data = read_segments(target_in)
        records = load_manifest(target_audio_dir).get("chunks", {})
        if not isinstance(records, dict):
            records = {}

        invalid = [
            item["id"] for item in data
            if not is_current(item, records.get(item["id"], {}), target_audio_dir, self.tts_provider, self.tts.voice)
        ]
        if invalid:
            raise RuntimeError(
                "Missing, changed or unverified audio: " + ", ".join(invalid) +
                f". Run Stage 3 (Audio) again to resume synthesis."
            )

        segments = [as_segment(item, target_audio_dir) for item in data]
        AudioAssembler(target_out, speed=target_speed, eq_profile=target_eq).assemble(segments)

        # Apply metadata tags
        meta = self.resolve_metadata(metadata)
        try:
            AudioEnhancer.apply_metadata(target_out, target_out, metadata=meta)
        except Exception as e:
            print(f"[Stage 4: Mastering] Warning: Could not write ID3 metadata: {e}")

        # Keep legacy aliases in sync
        if target_out != self.stage4_master_file:
            try:
                shutil.copyfile(target_out, self.stage4_master_file)
            except Exception:
                pass
        if target_out != self.master_file:
            try:
                shutil.copyfile(target_out, self.master_file)
            except Exception:
                pass

        self.save_timestamped_artifact("05_mastered", "mp3", target_out)
        print(f"[Stage 4: Mastering] Complete: Mastered audiobook ready at {target_out} ({target_speed:.2f}x tempo)")
        return target_out

    def run_stage_5_speed(
        self,
        speed: Optional[float] = None,
        input_file: Optional[str] = None,
        output_file: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Stage 5 (Speed / Flow Optimization): Adjusts audiobook speed/tempo (default: 1.15x) while preserving pitch."""
        target_speed = speed if speed is not None else getattr(self.profile, 'mastering_speed', 1.15)
        orig_1x = os.path.join(self.stage4_dir, 'mastered_1.0x_original.mp3')

        target_in = input_file or (
            self.named_master_file if os.path.isfile(self.named_master_file)
            else (orig_1x if os.path.isfile(orig_1x)
            else (self.stage4_master_file if os.path.isfile(self.stage4_master_file)
            else self.master_file))
        )
        if not target_in or not os.path.isfile(target_in):
            raise FileNotFoundError(f"Mastered audio file not found in {self.stage4_dir}. Run Stage 4 (Mastering) first.")

        target_out = output_file or self.named_master_file

        print(f"[Stage 5: Speed/Flow] Applying {target_speed:.2f}x tempo adjustment to: {target_in}")

        is_in_place = (os.path.abspath(target_in) == os.path.abspath(target_out))
        actual_dest = target_out if not is_in_place else target_out + ".tmp.mp3"

        AudioEnhancer.apply_speed(target_in, actual_dest, speed=target_speed)

        if is_in_place:
            os.replace(actual_dest, target_out)

        # Apply metadata tags
        meta = self.resolve_metadata(metadata)
        try:
            AudioEnhancer.apply_metadata(target_out, target_out, metadata=meta)
        except Exception as e:
            print(f"[Stage 5: Speed/Flow] Warning: Could not write ID3 metadata: {e}")

        if target_out != self.stage4_master_file and os.path.isfile(target_out):
            try:
                shutil.copyfile(target_out, self.stage4_master_file)
            except Exception:
                pass

        if target_out != self.master_file and os.path.isfile(target_out):
            try:
                shutil.copyfile(target_out, self.master_file)
            except Exception:
                pass

        self.save_timestamped_artifact(f"06_speed_{round(target_speed*100)}x", "mp3", target_out)
        print(f"[Stage 5: Speed/Flow] Complete: Optimized audiobook ready at {target_out} ({target_speed:.2f}x tempo)")
        return target_out

    def run_stage_6_metadata(
        self,
        input_file: Optional[str] = None,
        output_file: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Stage 6 (Metadata & Delivery Packaging): Tags MP3 with comprehensive ID3v2 metadata and exports as <pdf_name>.mp3."""
        target_in = input_file or (
            self.named_master_file if os.path.isfile(self.named_master_file)
            else (self.stage4_master_file if os.path.isfile(self.stage4_master_file)
            else self.master_file)
        )
        if not target_in or not os.path.isfile(target_in):
            raise FileNotFoundError(f"Mastered audio file not found in {self.stage4_dir}. Run Stage 4 (Mastering) first.")

        target_out = output_file or self.named_master_file
        meta = self.resolve_metadata(metadata)

        print(f"[Stage 6: Metadata & Export] Applying ID3v2 tags and packaging to: {target_out}")
        for k, v in meta.items():
            if v:
                print(f"  • {k.title()}: {v}")

        AudioEnhancer.apply_metadata(target_in, target_out, metadata=meta)

        # Sync legacy aliases
        if target_out != self.stage4_master_file:
            try:
                shutil.copyfile(target_out, self.stage4_master_file)
            except Exception:
                pass
        if target_out != self.master_file:
            try:
                shutil.copyfile(target_out, self.master_file)
            except Exception:
                pass

        self.save_timestamped_artifact("07_metadata", "mp3", target_out)
        print(f"[Stage 6: Metadata & Export] Complete: Delivery audiobook ready at {target_out}")
        return target_out

    def get_status(self) -> Dict[str, Any]:
        """Returns the status and artifact locations of all stages."""
        s0_txt = os.path.join(self.stage0_dir, 'text_cleaned.txt')
        s0_raw = os.path.join(self.stage0_dir, 'ocr_raw.txt')
        s1_seg = os.path.join(self.stage1_dir, 'segments.json')
        s2_ph = os.path.join(self.stage2_dir, 'phonetics.json')
        s3_man = os.path.join(self.stage3_dir, 'manifest.json')
        s4_named = self.named_master_file
        s4_mp3 = self.stage4_master_file

        has_stage0 = os.path.isfile(s0_txt) or os.path.isfile(s0_raw) or os.path.isfile(self.clean_file) or os.path.isfile(self.raw_file)
        has_stage1 = os.path.isfile(s1_seg) or os.path.isfile(self.segments_file)
        has_stage2 = os.path.isfile(s2_ph) or os.path.isfile(self.phonetics_file)
        has_stage3 = os.path.isfile(s3_man) or os.path.isfile(os.path.join(self.audio_dir, 'manifest.json'))
        has_stage4 = os.path.isfile(s4_named) or os.path.isfile(s4_mp3) or os.path.isfile(self.master_file)

        chunks_completed = 0
        chunks_total = 0
        if has_stage3:
            try:
                m = load_manifest(self.stage3_dir) or load_manifest(self.audio_dir)
                chunks = m.get("chunks", {})
                chunks_total = len(chunks)
                chunks_completed = sum(1 for c in chunks.values() if c.get("status") == "complete")
            except Exception:
                pass

        return {
            "book_name": self.book_name,
            "project_dir": self.project_dir,
            "stage0_ocr": has_stage0,
            "stage1_segments": has_stage1,
            "stage2_phonetics": has_stage2,
            "stage3_audio": has_stage3,
            "chunks_completed": chunks_completed,
            "chunks_total": chunks_total,
            "stage4_master": has_stage4,
            "final_master": s4_named if os.path.isfile(s4_named) else s4_mp3,
        }

    def print_dashboard(self):
        """Prints a human-friendly status overview for the book project."""
        st = self.get_status()
        print(f"\n=======================================================")
        print(f" Book Project: {st['book_name']}")
        print(f" Directory:    {st['project_dir']}")
        print(f"=======================================================")
        s0_mark = "[x]" if st["stage0_ocr"] else "[ ]"
        s1_mark = "[x]" if st["stage1_segments"] else "[ ]"
        s2_mark = "[x]" if st["stage2_phonetics"] else "[ ]"
        s3_mark = "[x]" if (st["stage3_audio"] and st["chunks_completed"] == st["chunks_total"] and st["chunks_total"] > 0) else "[ ]"
        s4_mark = "[x]" if st["stage4_master"] else "[ ]"

        audio_info = f"({st['chunks_completed']}/{st['chunks_total']} chunks)" if st['chunks_total'] > 0 else ""

        print(f" {s0_mark} Stage 0 (00_ocr/):       OCR Transcription")
        print(f" {s1_mark} Stage 1 (01_segments/):  Segmentation")
        print(f" {s2_mark} Stage 2 (02_phonetics/): Phonetics & Prosody")
        print(f" {s3_mark} Stage 3 (03_audio/):      Audio Synthesis {audio_info}")
        print(f" {s4_mark} Stage 4 (04_master/):     Studio Mastering (default 1.15x tempo)")
        print(f" {s4_mark} Stage 5 (speed/flow):     Speed & Flow Optimization (default: 1.15x)")
        print(f" {s4_mark} Stage 6 (metadata):       Metadata & Export ({self.book_name}.mp3)")
        print(f"-------------------------------------------------------")

        if not st["stage0_ocr"]:
            print(f" Next action: python run.py {self.book_name} 0")
        elif not st["stage1_segments"]:
            print(f" Next action: python run.py {self.book_name} 1")
        elif not st["stage2_phonetics"]:
            print(f" Next action: python run.py {self.book_name} 2")
        elif not st["stage3_audio"] or st["chunks_completed"] < st["chunks_total"]:
            print(f" Next action: python run.py {self.book_name} 3")
        elif not st["stage4_master"]:
            print(f" Next action: python run.py {self.book_name} 4")
        else:
            final_mp3 = self.named_master_file if os.path.isfile(self.named_master_file) else self.stage4_master_file
            print(f" Audiobook ready: {final_mp3} (1.15x fluid tempo, ID3 tagged)")
        print(f"=======================================================\n")

    # Friendly aliases
    run_ocr = run_stage_1_ocr
    run_segmentation = run_stage_1_segmentation
    run_phonetics = run_stage_2_phonetics
    run_audio = run_stage_3_audio
    run_mastering = run_stage_4_mastering
    run_speed = run_stage_5_speed
    run_tempo = run_stage_5_speed
    run_flow = run_stage_5_speed
    run_metadata = run_stage_6_metadata
    run_tag = run_stage_6_metadata
    run_export = run_stage_6_metadata
    run_package = run_stage_6_metadata


def parse_stage(stage_arg) -> int:
    """Parses numeric or named stage arguments."""
    if stage_arg is None:
        raise ValueError("Stage argument is required when not using --all.")
    mapping = {
        "0": 0, "ocr": 0,
        "1": 1, "segment": 1, "segmentation": 1,
        "2": 2, "phonetics": 2, "prosody": 2,
        "3": 3, "audio": 3, "tts": 3,
        "4": 4, "master": 4, "mastering": 4,
        "5": 5, "speed": 5, "tempo": 5, "flow": 5,
        "6": 6, "metadata": 6, "tag": 6, "tags": 6, "export": 6, "package": 6,
    }
    s = str(stage_arg).lower().strip()
    if s not in mapping:
        raise ValueError(
            f"Unknown stage '{stage_arg}'. Valid choices: 0 (ocr), 1 (segmentation), 2 (phonetics), 3 (audio), 4 (mastering), 5 (speed), 6 (metadata)."
        )
    return mapping[s]


def infer_book_and_project(book_or_project: Optional[str] = None) -> Tuple[str, str]:
    """Infers (book_name, project_dir) from a book name, path, or directory contents."""
    if book_or_project:
        val = normalize_cli_path(book_or_project.strip())
        if val.lower().endswith(".pdf") and os.path.isfile(val):
            book_name = os.path.splitext(os.path.basename(val))[0]
            project_dir = os.path.join("projects", re.sub(r'[^a-zA-Z0-9_-]', '_', book_name))
            return book_name, project_dir

        clean = re.sub(r'[^a-zA-Z0-9_-]', '_', val)
        if os.path.isdir(val):
            return os.path.basename(os.path.normpath(val)), val
        project_dir = os.path.join("projects", clean)
        return clean, project_dir

    # Check projects directory
    projects_dir = "projects"
    if os.path.isdir(projects_dir):
        existing = [d for d in os.listdir(projects_dir) if os.path.isdir(os.path.join(projects_dir, d)) and not d.startswith(".")]
        if len(existing) == 1:
            return existing[0], os.path.join(projects_dir, existing[0])

    # Check root for single PDF
    root_pdfs = [f for f in os.listdir(".") if f.lower().endswith(".pdf") and os.path.isfile(f)]
    if len(root_pdfs) == 1:
        name = os.path.splitext(root_pdfs[0])[0]
        return name, os.path.join("projects", re.sub(r'[^a-zA-Z0-9_-]', '_', name))

    return "", ""


def main():
    parser = argparse.ArgumentParser(
        description="""AWGP Audiobook Pipeline - Command-line runner.

Usage examples:
    python run.py my_book           # Show dashboard/status for 'my_book'
    python run.py my_book 0         # Run Stage 0 (OCR) for 'my_book'
    python run.py my_book all       # Run all stages sequentially
    
Stages:
    0 or ocr        : Extract text from PDF
    1 or segment    : Segment text
    2 or phonetics  : Apply phonetics & prosody
    3 or audio      : Synthesize chunks
    4 or master     : Master audio chunks
    5 or speed      : Tempo optimization
    6 or metadata   : ID3 metadata tagging & export
    all             : Run all stages sequentially

Resumability:
    Stages automatically skip if the output file already exists and is newer than the input file.
    Use the --force flag to force recomputation of a stage.
""",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # Support positional arguments: python run.py [book] [stage]
    parser.add_argument("book_pos", nargs="?", help="Book name or PDF path (e.g. brahma_sandhya or sample.pdf)")
    parser.add_argument("stage_pos", nargs="?", help="Stage: 0 (ocr), 1 (segmentation), 2 (phonetics), 3 (audio), 4 (mastering), 5 (speed), 6 (metadata), or 'all'")

    # Optional flags for granular control
    parser.add_argument("--project", help="Explicit project directory path")
    parser.add_argument("--book-name", help="Custom book identifier")
    parser.add_argument("--stage", help="Stage override")
    parser.add_argument("--all", action="store_true", help="Run all stages sequentially")
    parser.add_argument("--speed", type=float, default=None, help="Playback tempo multiplier (default: 1.15)")
    parser.add_argument("--eq", choices=["smooth", "balanced", "flat"], default=None, help="Equalizer profile: 'smooth' (warm anti-fatigue voice, default), 'balanced', 'flat'")
    parser.add_argument("--title", help="Audiobook title override for ID3 metadata")
    parser.add_argument("--artist", help="Author/Artist override for ID3 metadata")
    parser.add_argument("--album", help="Album name override for ID3 metadata")
    parser.add_argument("--year", help="Year override for ID3 metadata")
    parser.add_argument("--input", "-i", help="Custom input file path override")
    parser.add_argument("--output", "-o", help="Custom output file path override")
    parser.add_argument("--audio-dir", help="Custom audio directory override")
    parser.add_argument("--max-pages", type=int, help="Maximum pages to process during OCR")
    parser.add_argument("--page", type=int, help="Single 1-indexed page to process during OCR")
    parser.add_argument("--provider", choices=["edge", "google", "gemini", "azure", "studio", "gemini-studio", "google-studio", "sarvam", "sarvamai"], help="TTS provider override")
    parser.add_argument("--voice", help="TTS voice override")
    parser.add_argument("--status", action="store_true", help="Display project status dashboard")
    parser.add_argument("--force", action="store_true", help="Force recomputation of stages even if they are up to date")

    args = parser.parse_args()

    # Disambiguate positional arguments:
    # If first arg is a stage identifier (e.g. '0', 'ocr', '1') and no second arg:
    target_book = args.book_name or args.book_pos
    target_stage = args.stage_pos

    stage_keywords = {"0", "1", "2", "3", "4", "5", "6", "ocr", "segment", "segmentation", "phonetics", "audio", "master", "mastering", "speed", "tempo", "flow", "metadata", "tag", "tags", "export", "package", "all"}
    if target_book and str(target_book).lower() in stage_keywords and not target_stage:
        target_stage = target_book
        target_book = None

    # Flags override positional args
    if args.stage:
        target_stage = args.stage
    if args.all:
        target_stage = "all"

    inferred_book, inferred_project = infer_book_and_project(args.project or target_book)
    if not inferred_project:
        print("Error: Could not determine book project. Please specify a book name or PDF file.")
        print("Usage: python run.py <book_name> <stage>")
        print("Example: python run.py brahma_sandhya 0")
        return

    manager = ProjectManager(
        project_dir=inferred_project,
        tts_provider=args.provider,
        tts_voice=args.voice,
        book_name=inferred_book
    )

    # If no stage specified, or status requested, print dashboard
    if not target_stage or args.status:
        manager.print_dashboard()
        return

    pages_to_process = [args.page] if args.page else None
    cli_input = normalize_cli_path(args.input)

    if str(target_stage).lower() == "all":
        print(f"=== Running Full Pipeline for '{manager.book_name}' in '{manager.project_dir}' ===")
        pdf_input = cli_input if (cli_input and cli_input.lower().endswith(".pdf")) else None
        manager.run_stage_1_ocr(input_pdf=pdf_input, max_pages=args.max_pages, pages_to_process=pages_to_process)
        manager.run_stage_1_segmentation(force=args.force)
        manager.run_stage_2_phonetics(force=args.force)
        manager.run_stage_3_audio(audio_dir=args.audio_dir)
        manager.run_stage_4_mastering(audio_dir=args.audio_dir, speed=args.speed, eq_profile=args.eq, force=args.force)
        manager.run_stage_6_metadata()
        manager.print_dashboard()
    else:
        stage_num = parse_stage(target_stage)
        if stage_num == 0:
            pdf_input = cli_input or (normalize_cli_path(target_book) if (target_book and target_book.lower().endswith(".pdf")) else None)
            manager.run_stage_1_ocr(input_pdf=pdf_input, output_file=args.output, max_pages=args.max_pages, pages_to_process=pages_to_process)
        elif stage_num == 1:
            manager.run_stage_1_segmentation(input_text_file=cli_input, output_file=args.output, force=args.force)
        elif stage_num == 2:
            manager.run_stage_2_phonetics(input_segments_file=cli_input, output_file=args.output, force=args.force)
        elif stage_num == 3:
            manager.run_stage_3_audio(input_phonetics_file=cli_input, audio_dir=args.audio_dir or args.output)
        elif stage_num == 4:
            custom_meta = {}
            if args.title: custom_meta["title"] = args.title
            if args.artist: custom_meta["artist"] = args.artist
            if args.album: custom_meta["album"] = args.album
            if args.year: custom_meta["date"] = args.year
            manager.run_stage_4_mastering(
                input_phonetics_file=cli_input,
                audio_dir=args.audio_dir,
                output_file=args.output,
                speed=args.speed,
                metadata=custom_meta if custom_meta else None,
                eq_profile=args.eq,
                force=args.force,
            )
        elif stage_num == 5:
            custom_meta = {}
            if args.title: custom_meta["title"] = args.title
            if args.artist: custom_meta["artist"] = args.artist
            if args.album: custom_meta["album"] = args.album
            if args.year: custom_meta["date"] = args.year
            manager.run_stage_5_speed(
                speed=args.speed,
                input_file=cli_input,
                output_file=args.output,
                metadata=custom_meta if custom_meta else None,
            )
        elif stage_num == 6:
            custom_meta = {}
            if args.title: custom_meta["title"] = args.title
            if args.artist: custom_meta["artist"] = args.artist
            if args.album: custom_meta["album"] = args.album
            if args.year: custom_meta["date"] = args.year
            manager.run_stage_6_metadata(
                input_file=cli_input,
                output_file=args.output,
                metadata=custom_meta if custom_meta else None,
            )


if __name__ == '__main__':
    main()
