import { expectedChapterIdentity, assertCurrentChapterIdentity, type ChapterIdentity, type ExpectedChapterIdentity } from "./chapterIdentity";
import apiClient from "./apiClient";
import axios from "axios";
import type { ChapterDocument } from "../components/reader/chapterDocument";

import type {ReaderProviderResponse,StoryPermissionResponse,PortraitPermissionInput,ProviderInput,ProviderUpdate} from '../generated/api';
export type ReaderProviderWire=ReaderProviderResponse;
// Older installed servers omit capability/image fields; the reader treats these as unsupported.
export type ReaderProvider=Pick<ReaderProviderResponse,'id'|'name'|'kind'|'model'|'base_url'|'budget_usd'|'used_usd'|'reserved_usd'>&Partial<Omit<ReaderProviderResponse,'id'|'name'|'kind'|'model'|'base_url'|'budget_usd'|'used_usd'|'reserved_usd'|'input_price'|'output_price'>>&{input_price?:number|string;output_price?:number|string};
type WireTranslationJob=import('../generated/api').TranslationJobResponse;
type DerivativeIdentityKeys='chapter_key'|'manifest_epoch'|'manifest_revision'|'source_chapter_key'|'source_manifest_epoch'|'source_manifest_revision'|'source_identity_current'|'source_identity_inferred'|'chapter_archived'|'chapter_title_snapshot'|'chapter_number_snapshot'|'current_content_version';
export type TranslationVariant=Pick<WireTranslationJob,'id'|'language'|'status'|'completed_blocks'|'total_blocks'|'charged_usd'>&Partial<Pick<WireTranslationJob,DerivativeIdentityKeys|'source_version'|'error'>>&{document:ChapterDocument};
export type StoryTranslation=import('../generated/api').TranslationWorkspaceItem;
export type StoryTranslationsPage=import('../generated/api').TranslationWorkspacePage;
export type TranslationChapter=Omit<import('../generated/api').TranslationChapterItem,'current_content_version'>&Partial<Pick<import('../generated/api').TranslationChapterItem,'current_content_version'>>;
export type TranslationChaptersPage=Omit<import('../generated/api').TranslationChapterPage,'items'>&{items:TranslationChapter[]};
export interface TranslationBatchInput { chapter_identities?:({chapter_id:number}&ExpectedChapterIdentity)[]; chapter_ids: number[]; provider_id: number; language: string; external_consent: boolean; ao3_consent: boolean }
export interface TranslationBatchItem { chapter_id: number; chapter_number: number; title: string | null; outcome: string; job_id: number | null; source_version: string | null; blocks: number; estimated_max_usd: number; error: string | null }
export interface TranslationBatchReview {
  review_token: string; expires_at: string; provider: { id: number; name: string; kind: string; model: string; external: boolean };
  language: string; permission: { allowed: boolean; error: string | null; is_ao3: boolean };
  budget: { configured: boolean; available_usd: number; budget_usd: number; used_usd: number; reserved_usd: number };
  estimated_max_usd: number; queueable: number; total: number; items: TranslationBatchItem[];
}
export interface TranslationBatchResult { total: number; queued: number; items: TranslationBatchItem[] }
export type StoryPermission=Pick<StoryPermissionResponse,'translation'|'companion'|'ao3_consent'|'is_ao3'|'local'>&Partial<Pick<StoryPermissionResponse,'portrait'|'portrait_ao3_consent'|'portrait_requires_review'>>;
export interface CompanionAnswer {
  cached?: boolean;
  answer: string; through_chapter: number | null; charged_usd: number;
  citations: { chapter: number; block_id: string; quote: string; chapter_key?:string|null; source_version?:string|null }[];
}
export const readerToolsService = {
  translationChapters: async (novelId: number, offset = 0, limit = 50): Promise<TranslationChaptersPage> =>
    (await apiClient.get(`/reader/stories/${novelId}/translation-chapters`, { params: { offset, limit } })).data,
  reviewTranslationBatch: async (novelId: number, input: TranslationBatchInput): Promise<TranslationBatchReview> =>
    (await apiClient.post(`/reader/stories/${novelId}/translation-batch/preview`, input)).data,
  queueTranslationBatch: async (novelId: number, input: TranslationBatchInput, token: string): Promise<TranslationBatchResult> =>
    (await apiClient.post(`/reader/stories/${novelId}/translation-batch/jobs`, { ...input, review_token: token })).data,
  storyTranslations: async (novelId: number, offset = 0, limit = 50): Promise<StoryTranslationsPage> =>
    (await apiClient.get(`/reader/stories/${novelId}/translations`, { params: { offset, limit } })).data,
  exportStoryTranslations: async (novelId: number, jobIds: number[]): Promise<Blob> => {
    try { return (await apiClient.post(`/reader/stories/${novelId}/translations/epub`, { translation_job_ids: jobIds }, { responseType: "blob" })).data; }
    catch (error) {
      // Axios returns error bodies as Blobs too; retain bounded JSON details for the ordinary error UI.
      if (axios.isAxiosError(error) && error.response?.data instanceof Blob && error.response.data.size <= 65536 && error.response.data.type.includes("json")) {
        try { error.response.data = JSON.parse(await error.response.data.text()); } catch { /* Preserve the original transport error for malformed responses. */ }
      }
      throw error;
    }
  },
  confirmRead: async (novelId: number, chapter: number, version: string, readingRunKey?: string | null, identity?: ChapterIdentity) => {
    if (identity) assertCurrentChapterIdentity(novelId, identity);
    return (await apiClient.post(`/reader/companion/${novelId}/chapters/${chapter}/confirm-read`, { content_version: version, reading_run_key: readingRunKey ?? null,
      ...(identity ? expectedChapterIdentity(identity, version) : {}) })).data;
  },
  permission: async (novelId: number, providerId: number): Promise<StoryPermission> => (await apiClient.get(`/reader/permissions/${novelId}/${providerId}`)).data,
  setPortraitPermission: async (novelId:number,providerId:number,value:PortraitPermissionInput):Promise<StoryPermission> =>
    (await apiClient.patch(`/reader/permissions/${novelId}/${providerId}/portrait`,value)).data,
  setTranslationPermission: async (novelId: number, providerId: number, value: { translation: boolean; ao3_consent: boolean }): Promise<StoryPermission> =>
    (await apiClient.patch(`/reader/permissions/${novelId}/${providerId}/translation`, value)).data,
  setPermission: async (novelId: number, providerId: number, value: Record<string, boolean>): Promise<StoryPermission> => (await apiClient.put(`/reader/permissions/${novelId}/${providerId}`, value)).data,
  providers: async (): Promise<ReaderProvider[]> => (await apiClient.get("/reader/providers")).data,
  createProvider: async (value: ProviderInput) => (await apiClient.post("/reader/providers", value)).data,
  updateProvider: async (id: number, value: ProviderUpdate) => (await apiClient.put(`/reader/providers/${id}`, value)).data,
  variants: async (novelId: number, chapter: number, identity?:ChapterIdentity): Promise<TranslationVariant[]> =>
    (await apiClient.get(`/reader/translations/${novelId}/${chapter}`,identity?{params:expectedChapterIdentity(identity)}:undefined)).data,
  translate: async (novelId: number, chapter: number, providerId: number, language: string, consent: boolean, ao3Consent = false, identity?:ChapterIdentity, sourceVersion?:string) =>
    (await apiClient.post(`/reader/translations/${novelId}/${chapter}`, { ...(identity?expectedChapterIdentity(identity,sourceVersion):{}), provider_id: providerId, language, external_consent: consent, ao3_consent: ao3Consent })).data,
  preview: async (novelId: number, chapter: number, providerId: number, language: string, consent: boolean, ao3Consent = false, identity?:ChapterIdentity, sourceVersion?:string) =>
    (await apiClient.post(`/reader/translations/${novelId}/${chapter}/preview`, { ...(identity?expectedChapterIdentity(identity,sourceVersion):{}), provider_id: providerId, language, external_consent: consent, ao3_consent: ao3Consent }, { timeout: 130_000 })).data,
  action: async (jobId: number, action: "cancel" | "retry") =>
    (await apiClient.post(`/reader/translation-jobs/${jobId}`, { action })).data,
  exportEpub: async (jobId: number): Promise<Blob> =>
    (await apiClient.get(`/reader/translation-jobs/${jobId}/epub`, { responseType: "blob" })).data,
  question: async (novelId: number, providerId: number, question: string, consent: boolean, throughChapter?: number, ao3Consent = false): Promise<CompanionAnswer> =>
    (await apiClient.post(`/reader/companion/${novelId}/questions`, { provider_id: providerId, question, external_consent: consent, through_chapter: throughChapter, ao3_consent: ao3Consent }, { timeout: 135_000 })).data,
  glossaryEntries: async (novelId:number, language:string, offset=0):Promise<import('../generated/api').StoryGlossaryPage> =>
    (await apiClient.get(`/reader/glossary/${novelId}/entries`,{params:{language,offset,limit:50}})).data,
  glossary: async (novelId: number, value: Record<string, unknown>, identity:ChapterIdentity, sourceVersion:string):Promise<import('../generated/api').StoryGlossaryEntry> => {
    assertCurrentChapterIdentity(novelId,identity);
    return (await apiClient.post(`/reader/glossary/${novelId}`, {...value,...expectedChapterIdentity(identity,sourceVersion)})).data;
  },
};
