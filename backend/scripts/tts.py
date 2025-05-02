from kokoro import KPipeline
import soundfile as sf
from pydub import AudioSegment
import torch

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
