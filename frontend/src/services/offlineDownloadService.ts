import { chapterIdentity, sameChapterIdentity, assertCurrentChapterIdentity, type ChapterIdentity } from "./chapterIdentity";
import apiClient from './apiClient';
import { storageGeneration } from './accountStorage';
import { chapterService } from './chapterService';
import { offlineReaderStore, chapterAudioStore } from './offlineReaderStore';
import { offlineLibraryStore } from './offlineLibraryStore';
import { offlineTranslations } from './offlineTranslations';
import { audioService } from './audioService';
import { readerChapterDocument } from './chapterContracts';
import type { OfflineManifestPage, OfflineManifestChapter, OfflineTranslationContent } from '../generated/api';

export type OfflineCopyOptions = { audio: boolean; translations: boolean };
export type OfflineCopyPlan = {
  generation: number; libraryId: number; novelId: number; title: string;
  options: OfflineCopyOptions; chapters: OfflineManifestChapter[];
  estimatedBytes: number; audioCount: number; translationCount: number;
  unavailable: number; unknownVersion: number; translationsLimited: boolean;
  storage: { total_bytes: number; limit_bytes: number | null; remaining_bytes: number | null };
};
export type OfflineCopyResult = { text: number; audio: number; translations: number; failed: number };
const changed = () => new DOMException('The reading account or offline operation changed', 'AbortError');
const check = (generation: number, current: () => boolean) => {
  if (generation !== storageGeneration() || !current()) throw changed();
};

export const offlineDownloadService = {
  async plan(libraryId: number, novelId: number, wanted: 'next' | 'all', count: number,
    options: OfflineCopyOptions, current: () => boolean): Promise<OfflineCopyPlan> {
    const generation = storageGeneration(); check(generation, current);
    let position: number | null = null;
    let finishedCurrent = false;
    if (wanted === 'next') {
      const progress = await chapterService.getReadingProgress(novelId);
      check(generation, current); position = progress?.chapter_number ?? null;
      finishedCurrent = (progress?.percent ?? 0) >= 95;
    }
    const eligible = (row: OfflineManifestChapter) => row.downloaded && row.source_version
      && (wanted === 'all' || position === null || (finishedCurrent ? row.chapter_number > position : row.chapter_number >= position));
    const chapters: OfflineManifestChapter[] = [];
    let offset = 0, total = 0, title = '';
    let manifest:ChapterIdentity|null=null;
    do {
      check(generation, current);
      const page = (await apiClient.get<OfflineManifestPage>(`/reader/stories/${novelId}/offline-manifest`, { params: { offset, limit: 200, ...(manifest ? {expected_manifest_epoch:manifest.manifest_epoch,expected_manifest_revision:manifest.manifest_revision}:{}), ...(wanted === 'next' ? { followed_only: true, downloaded_only: true, ...(position !== null ? { from_chapter: position } : {}) } : {}) } })).data;
      check(generation, current);
      if (page.novel_id !== novelId || page.library_id !== libraryId || page.offset !== offset || page.chapters.length > 200
          || chapters.length + page.chapters.length > 20_000 || !Number.isSafeInteger(page.total) || page.total < 0)
        throw new Error('This selection changed or exceeds the 20,000-chapter review limit. Choose a smaller offline selection.');
      for(const row of page.chapters){
        const identity=chapterIdentity(row);if(!identity)throw new Error("The server has not supplied a verified chapter identity. Refresh Nexus before saving offline copies.");
        if(manifest && (manifest.manifest_epoch!==identity.manifest_epoch || manifest.manifest_revision!==identity.manifest_revision))throw new Error("The chapter list changed. Review offline copies again.");
        manifest=identity;
      }
      total = page.total; title = page.novel_title; chapters.push(...page.chapters);
      offset += page.chapters.length;
      if (!page.chapters.length && offset < total) throw new Error('The chapter list changed. Review offline copies again.');
    } while (offset < total && (wanted === 'all' || chapters.filter(eligible).length < count));
    const available = chapters.filter(eligible);
    const targets = wanted === 'all' ? available : available.slice(0, count);
    const storage = await offlineLibraryStore.budget(); check(generation, current);
    return { generation, libraryId, novelId, title, options: { ...options }, chapters: targets, storage,
      estimatedBytes: targets.reduce((sum, row) => sum + row.text_bytes_estimate + (options.audio ? row.audio?.bytes ?? 0 : 0)
        + (options.translations ? row.translations.reduce((size, item) => size + item.bytes_estimate, 0) : 0), 0),
      audioCount: options.audio ? targets.filter(row => row.audio).length : 0,
      translationCount: options.translations ? targets.reduce((sum, row) => sum + row.translations.length, 0) : 0,
      unavailable: chapters.filter(row => !row.downloaded).length,
      unknownVersion: chapters.filter(row => row.downloaded && !row.source_version).length,
      translationsLimited: options.translations && targets.some(row => row.translations_limited),
    };
  },
  async copy(plan: OfflineCopyPlan, current: () => boolean, progress: (done: number, total: number) => void): Promise<OfflineCopyResult> {
    const result = { text: 0, audio: 0, translations: 0, failed: 0 };
    check(plan.generation, current);
    for (const [index, row] of plan.chapters.entries()) {
      check(plan.generation, current);
      const identity=chapterIdentity(row);if(!identity)throw new Error("The reviewed chapter identity is missing. Review offline copies again.");
      try {
        assertCurrentChapterIdentity(plan.novelId,identity);
        const content = await chapterService.getChapterContentByNumber(row.chapter_number, plan.libraryId, plan.novelId,identity);
        check(plan.generation, current);
        if (!chapterIdentity(content) || !sameChapterIdentity(identity,chapterIdentity(content)!) || content.id !== row.id || content.novel_id !== plan.novelId || content.chapter_number !== row.chapter_number
          || content.document?.content_version !== row.source_version) throw new Error('The original changed; review offline copies again.');
        await offlineReaderStore.save({ ...content, library_id: plan.libraryId, novel_title: plan.title }, { pinned: true });
        check(plan.generation, current); result.text += 1;
      } catch (error) {
        check(plan.generation, current); result.failed += 1;
        if (error instanceof DOMException && error.name === 'AbortError') throw error;
        progress(index + 1, plan.chapters.length); continue;
      }
      if (plan.options.audio && row.audio) {
        check(plan.generation, current);
        try {
          const [blob, manifest] = await Promise.all([audioService.audio(row.audio.job_id), audioService.manifest(row.audio.job_id)]);
          check(plan.generation, current);
          if (!chapterIdentity(manifest) || !sameChapterIdentity(identity,chapterIdentity(manifest)!) || !blob.size || blob.size !== row.audio.bytes || manifest.job_id !== row.audio.job_id
            || manifest.source_version !== row.source_version || manifest.current_source === false) throw new Error('The recording changed; review it again.');
          await chapterAudioStore.save(plan.novelId, row.chapter_number, blob, manifest, () => plan.generation === storageGeneration() && current());
          check(plan.generation, current); result.audio += 1;
        } catch { check(plan.generation, current); result.failed += 1; }
      }
      if (plan.options.translations) for (const choice of row.translations) {
        check(plan.generation, current);
        try {
          const value = (await apiClient.get<OfflineTranslationContent>(`/reader/offline/translations/${choice.job_id}`)).data;
          check(plan.generation, current);
          const document = readerChapterDocument(value.document);
          if (!chapterIdentity(value) || !sameChapterIdentity(identity,chapterIdentity(value)!) || !document || value.id !== choice.job_id || value.novel_id !== plan.novelId || value.chapter_number !== row.chapter_number
            || value.status !== 'completed' || value.source_version !== row.source_version || value.language !== choice.language
            || value.completed_blocks !== value.total_blocks) throw new Error('The saved translation changed.');
          await offlineTranslations.save(plan.novelId, row.chapter_number, { ...value, document });
          check(plan.generation, current); result.translations += 1;
        } catch { check(plan.generation, current); result.failed += 1; }
      }
      progress(index + 1, plan.chapters.length);
    }
    return result;
  },
};
