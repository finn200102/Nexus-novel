import type { ExpectedChapterIdentity } from "./chapterIdentity";
import {audioManifestFromWire,type AudioManifest} from "./audioAlignment";
import apiClient from "./apiClient";

type WireAudioJob=import('../generated/api').AudioJobResponse;
type JobPresentationKeys='id'|'status'|'provider_id'|'provider_model'|'provider_voice'|'total_parts'|'completed_parts';
// Cache/test consumers need no timestamps; every presented wire field keeps its
// generated nullability, including unprovenanced recordings with no current key.
export type ServerAudioJob=Pick<WireAudioJob,JobPresentationKeys>&Partial<Omit<WireAudioJob,JobPresentationKeys|'audio_ready'>>&{audio_ready:boolean};
export type StoryAudioChapter=Omit<import('../generated/api').StoryAudioChapter,'latest_job'>&{latest_job:ServerAudioJob|null};
export type StoryAudioOverview=Omit<import('../generated/api').StoryAudioResponse,'chapters'>&{chapters:StoryAudioChapter[]};
export type StoryAudioBatch=Omit<import('../generated/api').StoryAudioBatchResponse,'outcomes'>&{outcomes:(Omit<import('../generated/api').StoryAudioOutcome,'job'>&{job:ServerAudioJob|null})[]};

export type AudioProviderConfig = {
  id: string;
  base_url: string;
  model: string;
  voice: string;
  language_code?: string;
  execution_mode: "browser" | "server";
};

// The server never receives the provider id or the browser/server execution mode.
function toServerProviderRequest(provider: AudioProviderConfig) {
  const request: Partial<AudioProviderConfig> = { ...provider };
  delete request.id;
  delete request.execution_mode;
  return { id: provider.id, request };
}

export const audioService = {
  async recordings(novelId:number,offset=0):Promise<Omit<import('../generated/api').StoryAudioRecordingPage,'items'>&{items:ServerAudioJob[]}>{
    const page=(await apiClient.get<import('../generated/api').StoryAudioRecordingPage>(`/audio/stories/${novelId}/recordings`,{params:{offset,limit:50}})).data;
    return {...page,items:page.items.map(row=>({...row,audio_ready:row.audio_ready===true}))};
  },
  async story(novelId: number, offset = 0, limit = 50, range?:{from_chapter:number;to_chapter:number}): Promise<StoryAudioOverview> {
    return (await apiClient.get(`/audio/stories/${novelId}`, { params: { offset, limit, ...range } })).data;
  },
  async createStory(novelId: number, input: { chapter_numbers: number[]; chapter_identities?:({chapter_number:number}&ExpectedChapterIdentity)[]; include_author_notes: boolean } & ({ voice_profile_id: number; provider?: never } | { voice_profile_id?: never; provider: AudioProviderConfig })): Promise<StoryAudioBatch> {
    // Explicit fields keep browser-only API keys out of backend job requests.
    const provider = input.provider;
    const body = { chapter_numbers: input.chapter_numbers, ...(input.chapter_identities?{chapter_identities:input.chapter_identities}:{}), include_author_notes: input.include_author_notes,
      ...(input.voice_profile_id ? { voice_profile_id: input.voice_profile_id } : provider ? { provider: {
        id: provider.id, base_url: provider.base_url, model: provider.model, voice: provider.voice,
        language_code: provider.language_code, execution_mode: provider.execution_mode,
      } } : {}),
    };
    return (await apiClient.post(`/audio/stories/${novelId}/jobs`, body)).data;
  },
  async providers() { return (await apiClient.get("/audio/providers")).data; },
  async check(provider: AudioProviderConfig) {
    const { id, request } = toServerProviderRequest(provider);
    return (await apiClient.post(`/audio/providers/${id}/check`, { provider_id: id, ...request })).data;
  },
  async preview(provider: AudioProviderConfig) {
    const { id, request } = toServerProviderRequest(provider);
    return (await apiClient.post(`/audio/providers/${id}/preview`, { provider_id: id, ...request })).data;
  },
  async create(input: Partial<ExpectedChapterIdentity> & { library_id: number; novel_id: number; chapter_number: number; voice_profile_id?: number; include_author_notes?: boolean; provider: AudioProviderConfig }): Promise<ServerAudioJob> {
    return (await apiClient.post("/audio/jobs", input)).data;
  },
  async get(id: number): Promise<ServerAudioJob> { return (await apiClient.get(`/audio/jobs/${id}`)).data; },
  async list(chapterId: number): Promise<ServerAudioJob[]> { return (await apiClient.get(`/audio/jobs?chapter_id=${chapterId}`)).data; },
  async retry(id: number): Promise<ServerAudioJob> { return (await apiClient.post(`/audio/jobs/${id}/retry`)).data; },
  async cancel(id: number): Promise<ServerAudioJob> { return (await apiClient.post(`/audio/jobs/${id}/cancel`)).data; },
  async remove(id: number): Promise<void> { await apiClient.delete(`/audio/jobs/${id}`); },
  async manifest(id:number):Promise<AudioManifest> {return audioManifestFromWire((await apiClient.get<import("../generated/api").AudioManifestResponse>(`/audio/jobs/${id}/manifest`)).data);},
  async audio(id: number): Promise<Blob> { return (await apiClient.get(`/audio/jobs/${id}/audio`, { responseType: "blob" })).data; },
};
