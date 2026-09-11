import os
import subprocess
from pathlib import Path


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
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

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

        Parameters
        ----------
        input_path:
            TTS source audio.

        output_path:
            Destination audio.

        lossless:
            If True, encode a WAV master instead of MP3.

        Notes
        -----
        The processing deliberately avoids:
            - synthetic brown/white noise
            - obvious artificial reverb
            - aggressive compression
            - excessive bass enhancement
            - excessive stereo widening

        These can initially make TTS appear more "human" in isolation but
        generally become fatiguing or obviously processed during long-form
        audiobook listening.
        """

        input_path = str(Path(input_path))
        output_path = str(Path(output_path))

        if not os.path.isfile(input_path):
            raise FileNotFoundError(input_path)

        # ==============================================================
        # SIGNAL CHAIN
        # ==============================================================
        #
        # 1. Resample into a clean mastering domain
        # 2. High-pass rumble removal
        # 3. Broad low-mid cleanup
        # 4. Gentle warmth
        # 5. Presence enhancement
        # 6. Dynamic de-essing
        # 7. Very gentle compression
        # 8. Subtle harmonic saturation
        # 9. Loudness normalization
        # 10. True-peak limiting
        #
        # The previous implementation used:
        #
        #   aecho + synthetic brown noise
        #
        # which is deliberately removed. A synthetic noise floor does not
        # make TTS inherently human; it can instead make pauses sound dirty.
        #
        # Likewise, a fixed echo does not simulate a recording booth well.
        # It creates a recognizable repeated reflection and can reduce
        # intelligibility of Sanskrit/Hindi consonants.
        #
        # FFmpeg provides dedicated de-essing, dynamics and loudness tools
        # that are better suited to spoken-word mastering.
        # ==============================================================

        filter_complex = (
            # ----------------------------------------------------------
            # CLEAN MASTERING DOMAIN
            # ----------------------------------------------------------
            "aresample=48000:resampler=soxr:precision=28,"

            # ----------------------------------------------------------
            # SUBSONIC / LOW-END CONTROL
            #
            # TTS normally has little useful energy below ~70 Hz.
            # Removing it creates headroom without making the voice thin.
            # ----------------------------------------------------------
            "highpass=f=65:p=2,"

            # ----------------------------------------------------------
            # PARAMETRIC VOICE EQ
            #
            # 110 Hz:
            #   extremely gentle warmth rather than the +4 dB boost from
            #   the original implementation.
            #
            # 250 Hz:
            #   slight reduction of synthetic/boxy coloration.
            #
            # 3200 Hz:
            #   controlled intelligibility/presence.
            #
            # 8000 Hz:
            #   very mild air reduction to tame digital brightness.
            #
            # anequalizer is used instead of several broad tonal filters
            # because the voice can be shaped more precisely.
            # ----------------------------------------------------------
            (
                "anequalizer="
                "c0 f=110 w=90 g=0.8 t=0|"
                "c0 f=250 w=120 g=-1.2 t=0|"
                "c0 f=3200 w=1400 g=0.7 t=0|"
                "c0 f=7800 w=3000 g=-0.8 t=0,"
            ),

            # ----------------------------------------------------------
            # DE-ESSING
            #
            # Neural TTS can produce sharp sibilant peaks, particularly
            # on स / श / ष / च / छ and their surrounding vowels.
            #
            # This is much preferable to globally cutting all treble.
            # ----------------------------------------------------------
            "deesser="
            "i=0.25:"
            "m=0.5:"
            "f=6500:"
            "s=0.35,"

            # ----------------------------------------------------------
            # VERY GENTLE VOCAL COMPRESSION
            #
            # Enough to stabilize narration but retain the natural
            # difference between important words and connective speech.
            #
            # Lower compression is intentional for audiobook listening.
            # ----------------------------------------------------------
            "acompressor="
            "threshold=-20dB:"
            "ratio=1.45:"
            "attack=18:"
            "release=140:"
            "makeup=1.0:"
            "knee=2.5,"

            # ----------------------------------------------------------
            # SUBTLE HARMONIC DENSITY
            #
            # TTS can have an unnaturally sterile waveform.
            # A tiny amount of controlled saturation can make the
            # midrange feel less mathematically clean.
            #
            # Extremely conservative settings are important.
            # ----------------------------------------------------------
            "asoftclip="
            "type=tanh:"
            "threshold=0.92:"
            "param=0.80,"

            # ----------------------------------------------------------
            # FINAL LOUDNESS / TRUE-PEAK CONTROL
            #
            # loudnorm performs EBU-R128 loudness normalization and
            # incorporates true-peak limiting.
            # ----------------------------------------------------------
            (
                "loudnorm="
                "I=-18:"
                "LRA=6:"
                "TP=-1.5:"
                "dual_mono=true:"
                "print_format=summary"
            )
        )

        # FFmpeg filtergraph expects one comma-separated graph.
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

    # ------------------------------------------------------------------
    # OPTIONAL HIGH-QUALITY MASTER
    # ------------------------------------------------------------------

    @classmethod
    def create_master_and_delivery(
        cls,
        input_path: str,
        master_wav_path: str,
        delivery_mp3_path: str,
    ):
        """
        Create a lossless mastering master first and then a delivery MP3.

        This is preferable to mastering directly to MP3 because all later
        processing/assembly can operate from the lossless master.
        """

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