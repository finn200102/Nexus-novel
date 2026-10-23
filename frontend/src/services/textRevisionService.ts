import apiClient from './apiClient';
import { expectedChapterIdentity, type ChapterIdentity } from './chapterIdentity';
import type { PassageAnchor } from '../components/reader/selectedPassage';
export type RevisionMode = 'proofreading' | 'reformat' | 'rewrite' | 'translation_polish';
export type StoryTextStyle = import('../generated/api').StoryTextStyleResponse;
export type RevisionPreview = Pick<import('../generated/api').TextRevisionPreviewResponse, 'original'|'draft'|'preview'|'mode'|'saved'|'source_version'>;
export const textRevisionService = {
  defaults: async (): Promise<{base_url:string;model:string}> => (await apiClient.get('/reader/text-revisions/local-defaults')).data,
  style: async (novelId: number): Promise<StoryTextStyle> => (await apiClient.get(`/reader/text-revisions/stories/${novelId}/style`)).data,
  saveStyle: async (novelId:number, value:StoryTextStyle):Promise<StoryTextStyle> => (await apiClient.put(`/reader/text-revisions/stories/${novelId}/style`, { expected_revision:value.revision, style_guide:value.style_guide })).data,
  preview: async (novelId:number, chapter:number, providerId:number, mode:RevisionMode, identity:ChapterIdentity, sourceVersion:string, selection:PassageAnchor|null, translationJobId?:number):Promise<RevisionPreview> => (await apiClient.post(`/reader/text-revisions/${novelId}/${chapter}/preview`, {
    provider_id:providerId, mode, ...expectedChapterIdentity(identity,sourceVersion),
    ...(selection?{selection:{content_version:selection.content_version,block_id:selection.block_id,text_offset:selection.text_offset,text_length:selection.text_length,quote:selection.quote}}:{}),
    ...(translationJobId?{translation_job_id:translationJobId}:{}),
  }, { timeout: 130_000 })).data,
};
