export interface OpenAICompatibleTtsConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  voice: string;
}

export type TtsProviderPresetId = "kokoro_mps" | "qwen3_mlx_4bit" | "custom";

export interface TtsProviderPreset {
  id: TtsProviderPresetId;
  label: string;
  description: string;
  config: Omit<OpenAICompatibleTtsConfig, "apiKey">;
}

export const TTS_PROVIDER_PRESETS: TtsProviderPreset[] = [
  {
    id: "kokoro_mps",
    label: "Kokoro · fast local",
    description: "Native Apple Metal service on port 8880. Best for quick chapter generation.",
    config: { baseUrl: "http://localhost:8880/v1", model: "kokoro", voice: "af_bella" },
  },
  {
    id: "qwen3_mlx_4bit",
    label: "Qwen3‑TTS 1.7B · quality local",
    description: "MLX 4-bit on port 8890. Higher-fidelity voices; uses more unified memory.",
    config: {
      baseUrl: "http://localhost:8890/v1",
      model: "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
      voice: "vivian",
    },
  },
  {
    id: "custom",
    label: "Custom OpenAI-compatible API",
    description: "Use a self-hosted or hosted provider with your own endpoint and key.",
    config: { baseUrl: "", model: "", voice: "" },
  },
];

export class TtsRequestError extends Error {
  constructor(
    message: string,
    public readonly retryable: boolean,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "TtsRequestError";
  }
}

const speechUrl = (baseUrl: string) => {
  const normalized = baseUrl.trim().replace(/\/+$/, "");
  return normalized.endsWith("/audio/speech") ? normalized : `${normalized}/audio/speech`;
};

export const ttsService = {
  async synthesize(text: string, config: OpenAICompatibleTtsConfig, signal?: AbortSignal): Promise<Blob> {
    let response: Response;
    try {
      response = await fetch(speechUrl(config.baseUrl), {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        ...(config.apiKey.trim() ? { Authorization: `Bearer ${config.apiKey.trim()}` } : {}),
      },
      body: JSON.stringify({
        model: config.model.trim() || "kokoro",
        voice: config.voice.trim() || "af_bella",
        input: text,
        response_format: "mp3",
      }),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new TtsRequestError("Could not reach the audio provider.", true);
    }
    if (!response.ok) {
      const retryable = response.status === 408 || response.status === 429 || response.status >= 500;
      throw new TtsRequestError(`Audio provider returned ${response.status}.`, retryable, response.status);
    }
    return response.blob();
  },
};

/**
 * Keeps individual provider calls bounded and gives the reader a meaningful
 * progress unit. Kokoro also splits internally, but client chunks make jobs
 * resumable after a tab refresh or a transient provider failure.
 */
export const splitTextForSynthesis = (text: string, maximumCharacters = 1_100): string[] => {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  const sentences = normalized.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [normalized];
  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    const next = current ? `${current} ${sentence.trim()}` : sentence.trim();
    if (current && next.length > maximumCharacters) {
      chunks.push(current);
      current = sentence.trim();
    } else if (!current && next.length > maximumCharacters) {
      for (let index = 0; index < next.length; index += maximumCharacters) {
        chunks.push(next.slice(index, index + maximumCharacters));
      }
      current = "";
    } else {
      current = next;
    }
  }
  if (current) chunks.push(current);
  return chunks;
};

/**
 * Individual provider responses are self-contained MP3/WAV files. Appending
 * their bytes creates an invalid multi-file stream which some browsers report
 * as a silent chapter. Decode them first and save one canonical WAV instead.
 */
export const mergeAudioSegments = async (segments: Blob[]): Promise<Blob> => {
  if (!segments.length) throw new Error("No generated audio segments were available.");
  const AudioContextConstructor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextConstructor || !window.OfflineAudioContext) {
    throw new Error("This browser cannot safely combine generated audio segments.");
  }
  const context = new AudioContextConstructor();
  try {
    const decoded = await Promise.all(segments.map(async (segment) => context.decodeAudioData((await segment.arrayBuffer()).slice(0))));
    const sampleRate = decoded[0].sampleRate;
    const channels = Math.max(...decoded.map((audio) => audio.numberOfChannels));
    const frameCount = decoded.reduce((sum, audio) => sum + Math.ceil(audio.duration * sampleRate), 0);
    const offline = new OfflineAudioContext(channels, Math.max(frameCount, 1), sampleRate);
    let offset = 0;
    for (const audio of decoded) {
      const source = offline.createBufferSource();
      source.buffer = audio;
      source.connect(offline.destination);
      source.start(offset);
      offset += audio.duration;
    }
    const rendered = await offline.startRendering();
    return new Blob([encodeWav(rendered)], { type: "audio/wav" });
  } finally {
    await context.close();
  }
};

const encodeWav = (audio: AudioBuffer): ArrayBuffer => {
  const channels = audio.numberOfChannels;
  const frameCount = audio.length;
  const bytesPerSample = 2;
  const dataLength = frameCount * channels * bytesPerSample;
  const output = new ArrayBuffer(44 + dataLength);
  const view = new DataView(output);
  const writeText = (offset: number, value: string) => [...value].forEach((character, index) => view.setUint8(offset + index, character.charCodeAt(0)));
  writeText(0, "RIFF");
  view.setUint32(4, 36 + dataLength, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, audio.sampleRate, true);
  view.setUint32(28, audio.sampleRate * channels * bytesPerSample, true);
  view.setUint16(32, channels * bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, dataLength, true);
  let offset = 44;
  for (let frame = 0; frame < frameCount; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      const value = Math.max(-1, Math.min(1, audio.getChannelData(Math.min(channel, audio.numberOfChannels - 1))[frame]));
      view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
      offset += bytesPerSample;
    }
  }
  return output;
};
