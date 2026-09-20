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


def validate_mp3(path):
    """Verify that an MP3 container exposes a non-empty audio stream."""
    target = Path(path)
    if not target.is_file() or target.stat().st_size <= 0:
        raise ValueError(f"missing or empty file {target.name}")
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name:format=duration",
                "-of", "default=noprint_wrappers=1", str(target),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise ValueError("ffprobe is missing; install ffmpeg to validate mastered audio") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"invalid MP3: {exc.stderr.decode(errors='replace')[-500:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("MP3 validation timed out") from exc
    fields = {}
    for line in result.stdout.decode(errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip()] = value.strip()
    if fields.get("codec_name") != "mp3":
        raise ValueError("file does not contain an MP3 audio stream")
    try:
        if float(fields.get("duration", "0")) <= 0:
            raise ValueError("MP3 has no non-empty audio stream")
    except ValueError as exc:
        if str(exc) == "MP3 has no non-empty audio stream":
            raise
        raise ValueError("MP3 duration is unavailable") from exc
    return True
