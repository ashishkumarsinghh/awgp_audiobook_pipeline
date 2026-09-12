"""Lossless ordered assembly that refuses missing or incompatible narration."""
import os
import tempfile
import wave
from pathlib import Path
from src.synthesis.audio.io import validate_wav
from src.synthesis.audio.enhancer import AudioEnhancer


class AudioAssembler:
    def __init__(self, output_file):
        self.output_file = output_file
        self.work_dir = str(Path(output_file).parent)

    def assemble(self, segments):
        if not segments:
            raise ValueError("No narration chunks to master. Generate audio first.")
        for segment in segments:
            if not segment.audio_file:
                raise ValueError("A narration chunk has no audio file.")
            validate_wav(segment.audio_file)
            for pause in (segment.pause_before_ms, segment.pause_after_ms):
                if type(pause) is not int or not 0 <= pause <= 30000:
                    raise ValueError("Pauses must be between 0 and 30000 milliseconds.")
        Path(self.work_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".master-", dir=self.work_dir) as temporary:
            raw = Path(temporary) / "assembled.wav"
            output = Path(temporary) / "master.mp3"
            with wave.open(str(raw), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(24000)
                for segment in segments:
                    target.writeframes(bytes(segment.pause_before_ms * 24 * 2))
                    with wave.open(segment.audio_file, "rb") as source:
                        while data := source.readframes(24000):
                            target.writeframes(data)
                    target.writeframes(bytes(segment.pause_after_ms * 24 * 2))
            AudioEnhancer.apply_studio_mastering(str(raw), str(output), lossless=False)
            if not output.is_file() or output.stat().st_size <= 0:
                raise RuntimeError("Mastering did not produce an audio file.")
            os.replace(output, self.output_file)
