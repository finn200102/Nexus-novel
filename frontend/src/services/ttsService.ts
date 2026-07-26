export interface OpenAICompatibleTtsConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  voice: string;
}

const speechUrl = (baseUrl: string) => {
  const normalized = baseUrl.trim().replace(/\/+$/, "");
  return normalized.endsWith("/audio/speech") ? normalized : `${normalized}/audio/speech`;
};

export const ttsService = {
  async synthesize(text: string, config: OpenAICompatibleTtsConfig, signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(speechUrl(config.baseUrl), {
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
    if (!response.ok) throw new Error(`TTS provider returned ${response.status}`);
    return response.blob();
  },
};
