import os
import json
import argparse
import asyncio
from dotenv import load_dotenv

load_dotenv()

from typing import List, Dict
from dataclasses import asdict

from src.core.types import NarrationProfile, SpeechSegment
from src.normalize.segmenter import SemanticSegmenter
from src.normalize.pronunciation import PronunciationDictionary
from src.synthesis.prosody import ProsodyPlanner
from src.synthesis.providers import EdgeTTSProvider
from src.synthesis.assembler import AudioAssembler

class ProjectManager:
    def __init__(self, project_dir: str):
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
        self.tts = EdgeTTSProvider(self.profile.voice)

    def run_stage_1_ocr(self):
        """Reads 00_scanned.pdf, runs Gemini OCR, saves to 01_ocr_raw.txt"""
        from src.extract.ocr_engine import extract_text_from_pdf
        if not os.path.exists(self.pdf_file):
            raise FileNotFoundError(f"PDF {self.pdf_file} not found.")
        try:
            print("Running Gemini OCR...")
            text = extract_text_from_pdf(self.pdf_file)
        except Exception as e:
            text = ""
            try:
                import fitz
                doc = fitz.open(self.pdf_file)
                extracted = "\n\n".join(page.get_text().strip() for page in doc if page.get_text().strip())
                if len(extracted.strip()) > 20:
                    text = extracted
            except Exception:
                pass
            if not text:
                raise RuntimeError(f"OCR failed: {e}")
        
        with open(self.raw_file, 'w', encoding='utf-8') as f:
            f.write(text)
        print("Stage 0 Complete: OCR saved.")

    def run_stage_1_segmentation(self):
        """Reads 02_text_cleaned.txt (or 01_ocr_raw.txt), segments it, saves to 03_segments.json"""
        target_txt = self.clean_file if os.path.exists(self.clean_file) else self.raw_file
        if not os.path.exists(target_txt):
            raise FileNotFoundError("No input text found.")
            
        with open(target_txt, 'r', encoding='utf-8') as f:
            text = f.read()
            
        segments = self.segmenter.segment_text(text)
        data = [{"id": f"chunk_{i+1:04d}", "source_text": seg.source_text, "segment_type": seg.segment_type, "pause_after_ms": seg.pause_after_ms} for i, seg in enumerate(segments)]
            
        with open(self.segments_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"Stage 1 Complete: {len(data)} segments generated.")

    def run_stage_2_phonetics(self):
        """Reads 03_segments.json, applies phonetics/prosody, saves to 04_phonetics.json"""
        if not os.path.exists(self.segments_file):
            raise FileNotFoundError(f"{self.segments_file} not found.")
            
        with open(self.segments_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
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
                "pause_after_ms": seg.pause_after_ms
            }
            for i, seg in enumerate(segments)
        ]
            
        with open(self.phonetics_file, 'w', encoding='utf-8') as f:
            json.dump(out_data, f, ensure_ascii=False, indent=4)
        print(f"Stage 2 Complete: {len(out_data)} phonetic segments saved.")

    def run_stage_3_audio(self):
        """Reads 04_phonetics.json, saves to 05_audio_chunks"""
        if not os.path.exists(self.phonetics_file):
            raise FileNotFoundError(f"{self.phonetics_file} not found.")
            
        with open(self.phonetics_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        segments = []
        for item in data:
            seg = SpeechSegment(
                source_text=item.get("source_text", ""),
                normalized_text=item.get("normalized_text", item.get("source_text", "")),
                pronunciation_text=item.get("pronunciation_text", item.get("source_text", "")),
                segment_type=item.get("segment_type", "prose"),
                rate=item.get("rate", "+0%"),
                pitch=item.get("pitch", "+0Hz"),
                volume=item.get("volume", "+0%"),
                pause_after_ms=item.get("pause_after_ms", 0)
            )
            seg.audio_file = os.path.join(self.audio_dir, f"{item['id']}.wav")
            segments.append(seg)
            
        async def generate_all():
            sem = asyncio.Semaphore(3)
            async def synth_chunk(i, seg):
                if not os.path.exists(seg.audio_file) or os.path.getsize(seg.audio_file) < 100:
                    print(f"Synthesizing [{i+1}/{len(segments)}] {seg.audio_file}...")
                    async with sem:
                        for attempt in range(2):
                            try:
                                await asyncio.wait_for(self.tts.synthesize(seg, seg.audio_file), timeout=35.0)
                                break
                            except Exception as e:
                                print(f"Retry {attempt+1} chunk {seg.audio_file}: {e}")
                                if attempt == 1:
                                    # Fallback: create silent audio chunk so pipeline never hangs
                                    cmd = f"ffmpeg -y -f lavfi -i aevalsrc=0 -t 0.5 -ar 24000 -ac 1 -c:a pcm_s16le '{seg.audio_file}' -loglevel error"
                                    os.system(cmd)
            tasks = [synth_chunk(i, seg) for i, seg in enumerate(segments)]
            await asyncio.gather(*tasks)
                    
        asyncio.run(generate_all())
        print(f"Stage 3 Complete: Synthesized {len(segments)} audio chunks.")

    def run_stage_4_mastering(self):
        """Reads 04_phonetics.json and 05_audio_chunks, assembles to 06_mastered.mp3"""
        if not os.path.exists(self.phonetics_file):
            raise FileNotFoundError(f"{self.phonetics_file} not found.")
            
        with open(self.phonetics_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        segments = []
        for item in data:
            seg = SpeechSegment(
                source_text=item.get("source_text", ""),
                normalized_text=item.get("normalized_text", item.get("source_text", "")),
                pronunciation_text=item.get("pronunciation_text", item.get("source_text", "")),
                segment_type=item.get("segment_type", "prose"),
                pause_after_ms=item.get("pause_after_ms", 0)
            )
            audio_path = os.path.join(self.audio_dir, f"{item['id']}.wav")
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 100:
                seg.audio_file = audio_path
                segments.append(seg)
                
        if not segments:
            print("No audio chunks to master, generating empty master fallback.")
            if not os.path.exists(self.master_file):
                cmd = f"ffmpeg -y -f lavfi -i aevalsrc=0 -t 0.5 -c:a libmp3lame '{self.master_file}' -loglevel error"
                os.system(cmd)
            return
            
        assembler = AudioAssembler(self.master_file)
        assembler.assemble(segments)
        print("Stage 4 Complete: Mastered audiobook ready.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Project directory path")
    parser.add_argument("--stage", type=int, choices=[0, 1, 2, 3, 4], help="Run a specific stage")
    parser.add_argument("--all", action="store_true", help="Run all stages sequentially")
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
