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
