"""Checked media operations; narration chunks use mono 24 kHz 16-bit PCM."""
import subprocess
import wave
from pathlib import Path


def run_ffmpeg(arguments):
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *map(str, arguments)],
                       check=True, capture_output=True, timeout=600)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is missing. Install ffmpeg and make it available on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg failed: {exc.stderr.decode(errors='replace')[-2000:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg exceeded the 10 minute timeout.") from exc


def validate_wav(path):
    try:
        with wave.open(str(path), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000):
                raise ValueError("expected mono 24 kHz 16-bit PCM")
            frames = audio.getnframes()
            if frames <= 0 or len(pcm := audio.readframes(frames)) != frames * 2:
                raise ValueError("empty or truncated PCM data")
            if not any(pcm):
                raise ValueError("narration contains only digital silence")
            return frames / 24000
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        raise ValueError(f"Invalid narration audio {Path(path).name}: {exc}") from exc
