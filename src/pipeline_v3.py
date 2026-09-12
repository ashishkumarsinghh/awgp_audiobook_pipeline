import os
import json
import argparse
import asyncio
from dotenv import load_dotenv

load_dotenv()

import fitz
from typing import List, Dict, Optional
from src.core.artifacts import atomic_write, write_json, read_segments
from src.synthesis.runner import synthesize_segments, as_segment, load_manifest, is_current

from src.core.types import NarrationProfile, SpeechSegment
from src.normalize.segmenter import SemanticSegmenter
from src.normalize.pronunciation import PronunciationDictionary
from src.synthesis.prosody import ProsodyPlanner
from src.synthesis.providers import EdgeTTSProvider, GeminiTTSProvider
from src.synthesis.assembler import AudioAssembler

class ProjectManager:
    def __init__(self, project_dir: str, tts_provider: Optional[str] = None, tts_voice: Optional[str] = None):
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.pdf_file = os.path.join(self.project_dir, '00_scanned.pdf')
        self.raw_file = os.path.join(self.project_dir, '01_ocr_raw.txt')
        self.clean_file = os.path.join(self.project_dir, '02_text_cleaned.txt')
        self.segments_file = os.path.join(self.project_dir, '03_segments.json')
        self.phonetics_file = os.path.join(self.project_dir, '04_phonetics.json')
        self.audio_dir = os.path.join(self.project_dir, '05_audio_chunks')
        self.master_file = os.path.join(self.project_dir, '06_mastered.mp3')
        os.makedirs(self.audio_dir, exist_ok=True)

        self.profile = NarrationProfile()
        self.segmenter = SemanticSegmenter(self.profile)
        self.pronunciation = PronunciationDictionary()
        self.prosody = ProsodyPlanner(self.profile)
        self.tts_provider = (tts_provider or os.environ.get('TTS_PROVIDER', 'edge')).lower()
        self.tts = self._get_tts_provider(tts_voice)

    def _get_tts_provider(self, voice: Optional[str] = None):
        voice = voice or os.environ.get('TTS_VOICE') or ('hi-IN-Wavenet-A' if self.tts_provider == 'gemini' else self.profile.voice)
        if self.tts_provider == 'gemini':
            return GeminiTTSProvider(voice)
        if self.tts_provider == 'edge':
            return EdgeTTSProvider(voice)
        raise ValueError(f'Unsupported TTS provider: {self.tts_provider}')

    def run_stage_1_ocr(self):
        """Reads 00_scanned.pdf, runs Gemini OCR, saves to 01_ocr_raw.txt"""
        from src.extract.ocr_engine import extract_text_from_pdf
        if not os.path.exists(self.pdf_file):
            raise FileNotFoundError(f"PDF {self.pdf_file} not found.")
        text = extract_text_from_pdf(self.pdf_file)
        if not text.strip():
            raise RuntimeError("OCR returned no text. Check the PDF and OCR configuration.")
        atomic_write(self.raw_file, text)
        self.invalidate_after("raw")
        print("Stage 0 Complete: OCR saved.")

    def run_stage_1_segmentation(self):
        """Reads 02_text_cleaned.txt (or 01_ocr_raw.txt), segments it, saves to 03_segments.json"""
        target_txt = self.clean_file if os.path.exists(self.clean_file) else self.raw_file
        if not os.path.exists(target_txt):
            raise FileNotFoundError("No input text found.")

        with open(target_txt, 'r', encoding='utf-8') as f:
            text = f.read()

        segments = self.segmenter.segment_text(text)
        if not segments:
            raise ValueError('No narration text found. Review OCR before segmentation.')
        data = [{"id": f"chunk_{i+1:04d}", "source_text": seg.source_text, "segment_type": seg.segment_type, "pause_after_ms": seg.pause_after_ms} for i, seg in enumerate(segments)]

        write_json(self.segments_file, data)
        self.invalidate_after('segments')
        print(f"Stage 1 Complete: {len(data)} segments generated.")

    def run_stage_2_phonetics(self):
        """Reads 03_segments.json, applies phonetics/prosody, saves to 04_phonetics.json"""
        if not os.path.exists(self.segments_file):
            raise FileNotFoundError(f"{self.segments_file} not found.")

        data = read_segments(self.segments_file)

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

        write_json(self.phonetics_file, out_data)
        self.invalidate_after('phonetics')
        print(f"Stage 2 Complete: {len(out_data)} phonetic segments saved.")

    def invalidate_after(self, stage):
        """Remove derived active artifacts; keep immutable history and reusable audio."""
        downstream = {
            "raw": [self.clean_file, self.segments_file, self.phonetics_file, self.master_file],
            "clean": [self.segments_file, self.phonetics_file, self.master_file],
            "segments": [self.phonetics_file, self.master_file],
            "phonetics": [self.master_file],
        }
        for path in downstream[stage]:
            if os.path.isfile(path):
                os.remove(path)

    def run_stage_3_audio(self):
        data = read_segments(self.phonetics_file)
        self.invalidate_after("phonetics")
        asyncio.run(synthesize_segments(data, self.audio_dir, self.tts, self.tts_provider))
        print(f"Stage 3 Complete: Verified {len(data)} audio chunks.")

    def run_stage_4_mastering(self):
        data = read_segments(self.phonetics_file)
        records = load_manifest(self.audio_dir).get("chunks", {})
        if not isinstance(records, dict):
            records = {}
        invalid = [item["id"] for item in data if not is_current(
            item, records.get(item["id"], {}), self.audio_dir, self.tts_provider, self.tts.voice)]
        if invalid:
            raise RuntimeError("Missing, changed or unverified audio: " + ", ".join(invalid) +
                               ". Run Audio again before mastering.")
        segments = [as_segment(item, self.audio_dir) for item in data]
        AudioAssembler(self.master_file).assemble(segments)
        print("Stage 4 Complete: Mastered audiobook ready.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Project directory path")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--stage", type=int, choices=[0, 1, 2, 3, 4], help="Run a specific stage")
    selection.add_argument("--all", action="store_true", help="Run all stages sequentially")
    args = parser.parse_args()

    manager = ProjectManager(args.project)

    if args.stage == 0 or args.all:
        manager.run_stage_1_ocr()
    if args.stage == 1 or args.all:
        manager.run_stage_1_segmentation()
    if args.stage == 2 or args.all:
        manager.run_stage_2_phonetics()
    if args.stage == 3 or args.all:
        manager.run_stage_3_audio()
    if args.stage == 4 or args.all:
        manager.run_stage_4_mastering()
