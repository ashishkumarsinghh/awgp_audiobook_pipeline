import subprocess
import os

class AudioEnhancer:
    """
    Applies professional audio mastering filters to TTS output to remove the 
    'robotic' vacuum sound and simulate a human recording in a studio booth.
    """
    @staticmethod
    def apply_studio_mastering(input_path: str, output_path: str):
        # The filtergraph does 4 critical acoustic enhancements:
        # 1. EQ: highpass at 80Hz (removes rumble), bass +3dB at 150Hz (adds chest warmth/proximity effect), treble -2dB at 8000Hz (softens digital sibilance).
        # 2. Reverb: aecho with a 25ms delay and 5% decay creates a 'recording booth' spatial reflection so it doesn't sound like a vacuum.
        # 3. Compression: Glues the dynamics so peaks aren't too sharp.
        # 4. Analog Noise Floor: Synthesizes a faint brown noise (-54dB equivalent) and mixes it in to fill the absolute dead silence between TTS words, which is the #1 giveaway of AI audio.
        
        filter_complex = (
            "[0:a]highpass=f=80,bass=g=4:f=120,treble=g=-2.5:f=7000,"
            "aecho=0.8:0.85:25:0.05,"
            "acompressor=threshold=-15dB:ratio=2:makeup=2[voice];"
            "anoisesrc=color=brown:amplitude=0.0015[noise];"
            "[voice][noise]amix=inputs=2:duration=first:dropout_transition=0[out]"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-q:a", "2",  # High quality VBR
            output_path
        ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

if __name__ == '__main__':
    print("Applying Studio Mastering...")
    enhancer = AudioEnhancer()
    enhancer.apply_studio_mastering(
        "/mnt/c/Users/ashis/.gemini/antigravity-cli/brain/27c1e63c-fecf-492d-a646-729f54feb151/brahma_sandhya_audiobook_v2.mp3",
        "/mnt/c/Users/ashis/.gemini/antigravity-cli/brain/27c1e63c-fecf-492d-a646-729f54feb151/brahma_sandhya_audiobook_studio.mp3"
    )
    print("Done! Studio version created.")