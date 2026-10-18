import apiClient from "./apiClient";
export type NarratorVoice = { id: number; name: string; language: string; status: string; transcript: string; error: string | null; preview_ready: boolean };
export type DefaultNarrator = { voice_profile_id: number | null; revision: number };
export const voiceService = {
  async getDefault(): Promise<DefaultNarrator> { return (await apiClient.get("/audio/voices/default")).data; },
  async setDefault(voice_profile_id: number | null, expected_revision: number): Promise<DefaultNarrator> { return (await apiClient.put("/audio/voices/default", { voice_profile_id, expected_revision })).data; },
  async capabilities(): Promise<{ configured: boolean; languages: string[] }> { return (await apiClient.get("/audio/voices/capabilities")).data; },
  async list(): Promise<NarratorVoice[]> { return (await apiClient.get("/audio/voices")).data; },
  async upload(input: {name: string; audio_base64: string; transcript: string; language: string; excerpt_start_seconds?: number; excerpt_duration_seconds?: number}): Promise<NarratorVoice> { return (await apiClient.post("/audio/voices", input, { timeout: 120_000 })).data; },
  async retry(id: number): Promise<NarratorVoice> { return (await apiClient.post(`/audio/voices/${id}/retry`)).data; },
  async remove(id: number) { await apiClient.delete(`/audio/voices/${id}`); },
  async preview(id: number): Promise<Blob> { return (await apiClient.get(`/audio/voices/${id}/preview`, { responseType: "blob" })).data; },
};
