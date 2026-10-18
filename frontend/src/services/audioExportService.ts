import apiClient from "./apiClient";

export type AudioExportJob = {
  id: number;
  novel_id: number;
  status: "queued" | "processing" | "retry_wait" | "completed" | "failed" | "cancelled";
  total_chapters: number;
  completed_chapters: number;
  audio_bytes: number | null;
  duration_seconds: number | null;
  error_code?: string | null;
  attempt_count?: number;
  max_attempts?: number;
  chapters: { audio_job_id: number; chapter_number: number; title: string | null; source_version: string | null; duration_seconds?: number | null; start_seconds?: number | null; end_seconds?: number | null }[];
  error: string | null;
  file_ready: boolean;
  created_at: string;
  updated_at: string;
};
export type PodcastEpisode = {
  id: number | null;
  source_audio_job_id: number;
  chapter_number: number;
  status: string;
  audio_bytes: number | null;
  duration_seconds: number | null;
  error_code: string | null;
  error: string | null;
};
export type StoryPodcast = {
  active: boolean;
  feed_url: string | null;
  format?: "mp3";
  ready: number;
  pending: number;
  failed: number;
  episodes: PodcastEpisode[];
  episodes_total?: number;
  episodes_offset?: number;
  episodes_limit?: number;
};

export const audioExportService = {
  async list(novelId: number): Promise<AudioExportJob[]> {
    return (await apiClient.get("/audio/exports", { params: { novel_id: novelId } })).data;
  },
  async create(novelId: number, audioJobIds: number[]): Promise<AudioExportJob> {
    return (await apiClient.post("/audio/exports", { novel_id: novelId, audio_job_ids: audioJobIds })).data;
  },
  async retry(id: number): Promise<AudioExportJob> { return (await apiClient.post(`/audio/exports/${id}/retry`)).data; },
  async cancel(id: number): Promise<AudioExportJob> { return (await apiClient.post(`/audio/exports/${id}/cancel`)).data; },
  async remove(id: number): Promise<void> { await apiClient.delete(`/audio/exports/${id}`); },
  async download(id: number): Promise<{ url: string }> { return (await apiClient.post(`/audio/exports/${id}/download`)).data; },
  async podcast(novelId: number, offset = 0, limit = 50): Promise<StoryPodcast> { return (await apiClient.get(`/audio/stories/${novelId}/podcast`, { params: { offset, limit } })).data; },
  async createPodcast(novelId: number): Promise<StoryPodcast> { return (await apiClient.post(`/audio/stories/${novelId}/podcast`)).data; },
  async retryPodcastEpisode(novelId: number, episodeId: number): Promise<PodcastEpisode> {
    return (await apiClient.post(`/audio/stories/${novelId}/podcast/episodes/${episodeId}/retry`)).data;
  },
  async revokePodcast(novelId: number): Promise<void> { await apiClient.delete(`/audio/stories/${novelId}/podcast`); },
};
