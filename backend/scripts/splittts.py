from kokoro import KPipeline
import soundfile as sf
from pydub import AudioSegment
import torch
import time
import os
import textwrap

def text_to_mp3(input_path='text.txt', output_path='output.mp3', lang_code='a', voice='af_heart'):
    # Read input text
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Split into ~300-character chunks
    chunks = textwrap.wrap(text, width=300)
    print(f"Split text into {len(chunks)} chunks.")

    # Initialize Kokoro TTS pipeline
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    print(f"Using device: {device}")
    pipeline = KPipeline(lang_code=lang_code)

    # Generate audio for each chunk
    print("Generating audio...")
    start = time.time()
    audio_data = []
    total_chunks = 0

    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i+1}/{len(chunks)}...")
        generator = pipeline(chunk, voice=voice)
        for _, _, audio_chunk in generator:
            audio_data.extend(audio_chunk)
            total_chunks += 1

    print(f"Generated {total_chunks} audio segments in {time.time() - start:.2f} seconds.")

    # Save as temp WAV
    wav_path = 'temp.wav'
    sf.write(wav_path, audio_data, samplerate=24000)

    # Convert to MP3
    print("Converting to MP3...")
    audio = AudioSegment.from_wav(wav_path)
    audio.export(output_path, format='mp3')
    os.remove(wav_path)
    print(f"Saved output to {output_path}")

def text_to_mp3(input_path='text.txt', output_path='output.mp3', lang_code='a', voice='af_heart'):
    # Read the input text
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Initialize Kokoro TTS pipeline
    pipeline = KPipeline(lang_code=lang_code)

    # Generate audio
    audio_data = []
    generator = pipeline(text, voice=voice)
    for _, _, audio_chunk in generator:
        audio_data.extend(audio_chunk)

    # Save as WAV
    wav_path = 'temp.wav'
    sf.write(wav_path, audio_data, samplerate=24000)

    # Convert to MP3
    audio = AudioSegment.from_wav(wav_path)
    audio.export(output_path, format='mp3')
    print(f"Saved output to {output_path}")



if __name__ == '__main__':
    text_to_mp3()

