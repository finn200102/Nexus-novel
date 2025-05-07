import queue
import threading

import sounddevice as sd
from kokoro import KPipeline


# Load and preprocess text by paragraphs (grouped in twos)
def load_paragraph_chunks(path, paragraphs_per_chunk=2):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # Split by paragraph (double newlines)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Group paragraphs into larger chunks
    chunks = [
        "\n\n".join(paragraphs[i : i + paragraphs_per_chunk])
        for i in range(0, len(paragraphs), paragraphs_per_chunk)
    ]
    return chunks


# Initialize Kokoro pipeline
pipeline = KPipeline(lang_code="a")  # American English

# Read from text file, 2 paragraphs per chunk
text_chunks = load_paragraph_chunks("text.txt", paragraphs_per_chunk=2)

# Thread-safe queue
audio_queue = queue.Queue()


# Generator thread
def generator_thread():
    for chunk in text_chunks:
        for _, _, audio in pipeline(chunk, voice="af_heart", split_pattern=None):
            audio_queue.put(audio)


# Player thread
def player_thread():
    while True:
        audio = audio_queue.get()
        if audio is None:
            break
        sd.play(audio, samplerate=24000)
        sd.wait()
        audio_queue.task_done()


# Run both threads
t1 = threading.Thread(target=generator_thread)
t2 = threading.Thread(target=player_thread)
t1.start()
t2.start()

# Clean shutdown
t1.join()
audio_queue.put(None)
t2.join()
