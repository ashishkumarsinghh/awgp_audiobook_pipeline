import os
import subprocess
from typing import List
from src.core.types import SpeechSegment

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
            cmd = f"ffmpeg -y -f lavfi -i aevalsrc=0 -t {duration_sec} -ar 24000 -ac 1 -c:a pcm_s16le {output_path} > /dev/null 2>&1"
            os.system(cmd)

    def assemble(self, segments: List[SpeechSegment]):
        print(f"[Assembler] Assembling {len(segments)} segments into {self.output_file}...")
        
        concat_file_path = os.path.join(self.work_dir, "concat_list.txt")
        
        with open(concat_file_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments):
                if not seg.audio_file or not os.path.exists(seg.audio_file):
                    continue
                
                # Write the actual audio chunk (.wav)
                f.write(f"file '{os.path.abspath(seg.audio_file)}'\n")
                
                # If there's a pause after, inject a silent chunk (.wav)
                if seg.pause_after_ms > 0:
                    silence_file = os.path.join(self.work_dir, f"silence_{seg.pause_after_ms}ms.wav")
                    self._generate_silence(seg.pause_after_ms, silence_file)
                    f.write(f"file '{os.path.abspath(silence_file)}'\n")
                    
        # Concatenate using ffmpeg
        print("[Mastering] Concatenating and mastering lossless WAVs...")
        mastering_filter = "loudnorm=I=-18:LRA=11:TP=-1.5"
        cmd = f"ffmpeg -y -f concat -safe 0 -i {concat_file_path} -af {mastering_filter} -c:a libmp3lame -q:a 2 {self.output_file} > /dev/null 2>&1"
        
        exit_code = os.system(cmd)
        if exit_code == 0:
            print(f"[Mastering] Final output ready at {self.output_file}")
        else:
            print(f"[Mastering] Failed to assemble audio. Ensure ffmpeg is installed.")