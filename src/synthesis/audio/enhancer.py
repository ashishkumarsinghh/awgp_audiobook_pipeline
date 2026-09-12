import os
import subprocess
from pathlib import Path
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
    ):
        """
        Apply audiobook-oriented mastering.
        """

        input_path = str(Path(input_path))
        output_path = str(Path(output_path))

        if not os.path.isfile(input_path):
            raise FileNotFoundError(input_path)

        filter_complex = (
            "aresample=48000:resampler=soxr:precision=28,",
            "highpass=f=65:p=2,",
            (
                "anequalizer="
                "c0 f=110 w=90 g=0.8 t=0|"
                "c0 f=250 w=120 g=-1.2 t=0|"
                "c0 f=3200 w=1400 g=0.7 t=0|"
                "c0 f=7800 w=3000 g=-0.8 t=0,"
            ),
            "deesser=i=0.25:m=0.5,",
            "acompressor="
            "threshold=-20dB:"
            "ratio=1.45:"
            "attack=18:"
            "release=140:"
            "makeup=1.0:"
            "knee=2.5,",
            "asoftclip="
            "type=tanh:"
            "threshold=0.92:"
            "param=0.80,",
            (
                "loudnorm="
                "I=-18:"
                "LRA=6:"
                "TP=-1.5:"
                "dual_mono=true:"
                "print_format=summary"
            )
        )

        filter_graph = "".join(filter_complex)

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
    ):
        cls.apply_studio_mastering(
            input_path=input_path,
            output_path=master_wav_path,
            lossless=True,
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