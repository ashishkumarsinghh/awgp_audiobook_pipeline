import os
import subprocess
from pathlib import Path
from typing import Optional, Dict
from src.synthesis.audio.io import run_ffmpeg


class AudioEnhancer:
    """
    Professional post-processing/mastering for neural TTS audiobook audio.

    Goal:
        Make synthetic TTS sound less clinical/robotic and more like a
        clean, intimate spoken-word audiobook recording.

    Processing philosophy:
        - Do NOT add obvious artificial room reverb.
        - Do NOT add audible synthetic noise between words.
        - Preserve natural TTS micro-dynamics.
        - Control harshness/sibilance rather than simply rolling off treble.
        - Add subtle warmth/presence.
        - Use gentle compression rather than radio-style compression.
        - Normalize to a controlled audiobook loudness target.
        - Preserve headroom and avoid clipping.

    The class intentionally uses FFmpeg-native filters so the pipeline remains
    deterministic and portable.

    Recommended input:
        Prefer WAV/PCM or the highest-quality audio produced by the TTS engine.
        Avoid repeatedly encoding MP3 before mastering.

    Recommended output:
        AAC/MP3 for delivery, but ideally keep a lossless WAV master as well.
    """

    # ------------------------------------------------------------------
    # MASTERING PROFILE
    # ------------------------------------------------------------------

    SAMPLE_RATE = 48000

    # Spoken-word audiobook target.
    #
    # -18 LUFS is deliberately chosen instead of pushing the voice toward
    # podcast/radio loudness. This leaves the narration comfortable for
    # long listening sessions and retains useful dynamics.
    TARGET_LUFS = -18.0
    TARGET_LRA = 6.0
    TRUE_PEAK = -1.5

    EQ_PROFILES = {
        "smooth": (
            # Warm anti-fatigue equalizer profile based on calibrated user curve:
            # 62Hz: +11dB, 125Hz: +11dB, 250Hz: +8dB, 500Hz: +3dB,
            # 1kHz: -3dB, 2kHz: -6dB, 4kHz: -10dB, 8kHz: -12dB, 16kHz: -12dB.
            # Uses linear zero-phase FIR equalizer to prevent phase distortion and smearing.
            "highpass=f=55:p=2,"
            "firequalizer=gain_entry='"
            "entry(0, 10); "
            "entry(62, 11); "
            "entry(125, 11); "
            "entry(250, 8); "
            "entry(500, 3); "
            "entry(1000, -3); "
            "entry(2000, -6); "
            "entry(4000, -10); "
            "entry(8000, -12); "
            "entry(16000, -12)"
            "':zero_phase=on,"
        ),
        "balanced": (
            # Subtle broadcast studio vocal enhancement
            "highpass=f=65:p=2,"
            "anequalizer="
            "c0 f=110 w=90 g=0.8 t=0|"
            "c0 f=250 w=120 g=-1.2 t=0|"
            "c0 f=3200 w=1400 g=0.7 t=0|"
            "c0 f=7800 w=3000 g=-0.8 t=0,"
        ),
        "flat": (
            "highpass=f=50:p=2,"
        ),
    }

    @staticmethod
    def _run(cmd):
        run_ffmpeg(cmd[1:])

    @classmethod
    def apply_studio_mastering(
        cls,
        input_path: str,
        output_path: str,
        *,
        lossless: bool = False,
        speed: float = 1.15,
        eq_profile: str = "smooth",
        target_lufs: float = -18.0,
        true_peak: float = -1.5,
    ):
        """
        Apply audiobook-oriented mastering with warm anti-fatigue EQ and optional pitch-preserving tempo adjustment (default: 1.15x).
        """

        input_path = str(Path(input_path))
        output_path = str(Path(output_path))

        if not os.path.isfile(input_path):
            raise FileNotFoundError(input_path)

        eq_filter = cls.EQ_PROFILES.get((eq_profile or "smooth").lower(), cls.EQ_PROFILES["smooth"])

        filters = [
            "aresample=48000:resampler=soxr:precision=28,",
            eq_filter,
            "deesser=i=0.30:m=0.5,",
            "acompressor="
            "threshold=-21dB:"
            "ratio=1.5:"
            "attack=20:"
            "release=160:"
            "makeup=1.0:"
            "knee=2.8,",
            "asoftclip="
            "type=tanh:"
            "threshold=0.92:"
            "param=0.80,",
        ]

        if speed and float(speed) != 1.0:
            filters.append(f"atempo={float(speed)},")

        filters.append(
            "loudnorm="
            f"I={target_lufs}:"
            "LRA=6:"
            f"TP={true_peak}:"
            "dual_mono=true:"
            "print_format=summary"
        )

        filter_graph = "".join(filters)

        if lossless:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-filter_complex",
                filter_graph,
                "-ar",
                str(cls.SAMPLE_RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s24le",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-filter_complex",
                filter_graph,
                "-ar",
                str(cls.SAMPLE_RATE),
                "-ac",
                "1",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-id3v2_version",
                "3",
                output_path,
            ]

        cls._run(cmd)

    @classmethod
    def create_master_and_delivery(
        cls,
        input_path: str,
        master_wav_path: str,
        delivery_mp3_path: str,
        *,
        eq_profile: str = "smooth",
        speed: float = 1.15,
    ):
        cls.apply_studio_mastering(
            input_path=input_path,
            output_path=master_wav_path,
            lossless=True,
            eq_profile=eq_profile,
            speed=speed,
        )

        cls._encode_mp3(
            input_path=master_wav_path,
            output_path=delivery_mp3_path,
        )

    @staticmethod
    def _encode_mp3(
        input_path: str,
        output_path: str,
        bitrate: str = "192k",
    ):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-id3v2_version",
            "3",
            output_path,
        ]

        AudioEnhancer._run(cmd)

    @classmethod
    def apply_speed(
        cls,
        input_path: str,
        output_path: str,
        speed: float = 1.15,
        bitrate: str = "192k",
    ):
        """Applies pitch-preserving tempo adjustment to an existing audio file."""
        input_path = str(Path(input_path))
        output_path = str(Path(output_path))

        if not os.path.isfile(input_path):
            raise FileNotFoundError(input_path)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-filter:a",
            f"atempo={float(speed)}",
            "-ar",
            str(cls.SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-id3v2_version",
            "3",
            output_path,
        ]

        cls._run(cmd)

    @classmethod
    def apply_metadata(
        cls,
        input_path: str,
        output_path: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Writes standard ID3v2 metadata tags to an MP3 file losslessly (without re-encoding audio).
        If output_path is omitted or identical to input_path, safely performs an in-place update.
        """
        input_path = str(Path(input_path))
        dest_path = str(Path(output_path)) if output_path else input_path

        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Audio file not found for metadata tagging: {input_path}")

        meta = metadata or {}
        is_in_place = (os.path.abspath(input_path) == os.path.abspath(dest_path))
        tmp_dest = dest_path if not is_in_place else dest_path + ".tmp.mp3"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-c",
            "copy",
        ]

        tag_map = {
            "title": "title",
            "artist": "artist",
            "album": "album",
            "album_artist": "album_artist",
            "date": "date",
            "year": "date",
            "genre": "genre",
            "publisher": "publisher",
            "comment": "comment",
            "track": "track",
            "disc": "disc",
            "composer": "composer",
        }

        for key, val in meta.items():
            if val is not None and str(val).strip():
                tag_name = tag_map.get(key.lower(), key.lower())
                cmd.extend(["-metadata", f"{tag_name}={str(val).strip()}"])

        cmd.extend([
            "-id3v2_version",
            "3",
            tmp_dest,
        ])

        cls._run(cmd)

        if is_in_place:
            os.replace(tmp_dest, dest_path)

        return dest_path