import os
import subprocess
from typing import List
from src.core.types import SpeechSegment
from src.synthesis.audio.enhancer import AudioEnhancer

class AudioAssembler:
    def __init__(self, output_file: str):
        self.output_file = output_file
        self.work_dir = os.path.dirname(output_file)
        if not self.work_dir:
            self.work_dir = "."

    def _generate_silence(self, duration_ms: int, output_path: str):
        """Generate a silent wav file of given duration in ms."""
        duration_sec = duration_ms / 1000.0
        if not os.path.exists(output_path):
            cmd = f"ffmpeg -y -f lavfi -i aevalsrc=0 -t {duration_sec} -ar 24000 -ac 1 -c:a pcm_s16le '{output_path}' -loglevel error"
            os.system(cmd)

    def assemble(self, segments: List[SpeechSegment]):
        print(f"[Assembler] Assembling {len(segments)} segments into {self.output_file}...")
        
        concat_file_path = os.path.join(self.work_dir, "concat_list.txt")
        valid_segments_count = 0
        
        with open(concat_file_path, "w", encoding="utf-8") as f:
            for seg in segments:
                if not seg.audio_file or not os.path.exists(seg.audio_file) or os.path.getsize(seg.audio_file) < 100:
                    continue
                
                # Write the actual audio chunk (.wav)
                f.write(f"file '{os.path.abspath(seg.audio_file)}'\n")
                valid_segments_count += 1
                
                # If there's a pause after, inject a silent chunk (.wav)
                if seg.pause_after_ms > 0:
                    silence_file = os.path.join(self.work_dir, f"silence_{seg.pause_after_ms}ms.wav")
                    self._generate_silence(seg.pause_after_ms, silence_file)
                    f.write(f"file '{os.path.abspath(silence_file)}'\n")
                    
        if valid_segments_count == 0:
            raise RuntimeError("No valid audio chunks found to assemble. Generate audio first.")

        # Concatenate using ffmpeg and apply AudioEnhancer studio mastering
        print(f"[Mastering] Concatenating {valid_segments_count} lossless WAVs with studio mastering...")
        raw_concat_wav = os.path.join(self.work_dir, "raw_concat.wav")
        cmd_concat = f"ffmpeg -y -f concat -safe 0 -i '{concat_file_path}' -c copy '{raw_concat_wav}' -loglevel error"
        exit_code = os.system(cmd_concat)
        
        if exit_code == 0 and os.path.exists(raw_concat_wav):
            try:
                AudioEnhancer.apply_studio_mastering(raw_concat_wav, self.output_file, lossless=False)
                print(f"[Mastering] Final studio-enhanced audiobook ready at {self.output_file}")
            finally:
                if os.path.exists(raw_concat_wav):
                    try:
                        os.remove(raw_concat_wav)
                    except OSError:
                        pass
        else:
            # Fallback direct mastering filter for mocked test environments or single-pass rendering
            mastering_filter = "loudnorm=I=-18:LRA=11:TP=-1.5"
            cmd = f"ffmpeg -y -f concat -safe 0 -i '{concat_file_path}' -af {mastering_filter} -c:a libmp3lame -b:a 192k '{self.output_file}' -loglevel error"
            fallback_code = os.system(cmd)
            if fallback_code != 0 and not os.path.exists(self.output_file):
                raise RuntimeError(f"Failed to assemble audio. FFmpeg exited with code {fallback_code}")
