import apiClient from "./apiClient";

export type ServerAudioJob = {
  id: number;
  status: "queued" | "processing" | "retry_wait" | "completed" | "failed" | "cancelled";
  provider_id: string;
  provider_model: string;
  provider_voice: string;
  total_parts: number;
  completed_parts: number;
  error?: string | null;
  error_code?: string | null;
  audio_ready: boolean;
};

export type AudioProviderConfig = {
  id: string;
  base_url: string;
  model: string;
  voice: string;
  language_code?: string;
  execution_mode: "browser" | "server";
};

export const audioService = {
  async providers() { return (await apiClient.get("/audio/providers")).data; },
  async check(provider: Omit<AudioProviderConfig, "id" | "execution_mode">) { return (await apiClient.post("/audio/providers/check", provider)).data; },
  async preview(provider: Omit<AudioProviderConfig, "id" | "execution_mode">) { return (await apiClient.post("/audio/providers/preview", provider)).data; },
  async create(input: { library_id: number; novel_id: number; chapter_number: number; provider: AudioProviderConfig }): Promise<ServerAudioJob> {
    return (await apiClient.post("/audio/jobs", input)).data;
  },
  async get(id: number): Promise<ServerAudioJob> { return (await apiClient.get(`/audio/jobs/${id}`)).data; },
  async list(chapterId: number): Promise<ServerAudioJob[]> { return (await apiClient.get(`/audio/jobs?chapter_id=${chapterId}`)).data; },
  async retry(id: number): Promise<ServerAudioJob> { return (await apiClient.post(`/audio/jobs/${id}/retry`)).data; },
  async cancel(id: number): Promise<ServerAudioJob> { return (await apiClient.post(`/audio/jobs/${id}/cancel`)).data; },
  async audio(id: number): Promise<Blob> { return (await apiClient.get(`/audio/jobs/${id}/audio`, { responseType: "blob" })).data; },
};
