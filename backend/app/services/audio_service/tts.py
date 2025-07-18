import os
import re
import subprocess
from pathlib import Path
from pydub import AudioSegment
import tempfile

# Constants
TMP_DIR = "/Users/finng/Home/Programmieren/Projects/nexus-novel/backend/tmp"
FIXED_DIR = os.path.join(TMP_DIR, "fixed")
OUTPUT_WAV = "combined.wav"
OUTPUT_MP3 = "output.mp3"


def numerical_sort(path):
    match = re.search(r'file_(\d+)\.wav$', path.name)
    return int(match.group(1)) if match else float('inf')


def run_koko_tts(input_text, script_path, tmp_dir):
    paragraph_list = input_text.strip().split("\n\n")
    os.makedirs(TMP_DIR, exist_ok=True)

    for idx, para in enumerate(paragraph_list):
        output_wav = os.path.join(tmp_dir, f"file_{idx}.wav")
        args = [script_path, "text", para, "-o", output_wav]
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"🗣️  Generated: file_{idx}.wav")


def convert_to_16bit_wavs(input_dir, fixed_dir):
    os.makedirs(fixed_dir, exist_ok=True)
    files = sorted(Path(input_dir).glob("file_*.wav"), key=numerical_sort)

    for wav in files:
        output = Path(fixed_dir) / wav.name
        cmd = [
            "ffmpeg", "-y", "-i", str(wav),
            "-af", "dynaudnorm",
            "-ar", "24000", "-ac", "2", "-sample_fmt", "s16",
            str(output)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"🔧 Converted: {wav.name}")


def combine_and_export_audio(fixed_dir, output_wav, output_mp3):
    files = sorted(Path(fixed_dir).glob("file_*.wav"), key=numerical_sort)
    combined = AudioSegment.silent(duration=0)

    for f in files:
        audio = AudioSegment.from_wav(f).normalize()
        combined += AudioSegment.silent(duration=100) + audio
        print(f"🔗 Added: {f.name}")


    Path(output_wav).parent.mkdir(parents=True, exist_ok=True)
    Path(output_mp3).parent.mkdir(parents=True, exist_ok=True)

    combined.export(output_wav, format="wav")
    print(f"✅ Exported WAV: {output_wav}")

    combined.export(output_mp3, format="mp3", bitrate="192k")
    print(f"🎵 Exported MP3: {output_mp3}")


def text_to_mp3(input_text, voice='af_heart', output_path='output.mp3'):
    # Resolve koko binary path
    relative_path = '../../../../tools/Kokoros/target/release/koko'
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), relative_path))
     
    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"Temporary directory: {tmp_dir}")


        fixed_dir = os.path.join(tmp_dir, "fixed")
        os.makedirs(fixed_dir)




        # 1. Generate raw .wav files
        run_koko_tts(input_text, script_path, tmp_dir)

        # 2. Convert to 16-bit .wav
        convert_to_16bit_wavs(tmp_dir, fixed_dir)

        # 3. Combine and export
        combine_and_export_audio(fixed_dir, OUTPUT_WAV, output_path)




# If run directly
if __name__ == "__main__":
    # Place your full text here (or load from file)
    with open("input.txt", "r") as f:
        text = f.read()

    text_to_mp3(text)

