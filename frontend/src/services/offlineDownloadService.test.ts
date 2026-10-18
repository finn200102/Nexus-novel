import {fixtureChapterIdentity as identity} from "../../tests/fixtures/chapterIdentity";
import { beforeEach, expect, it, vi } from 'vitest';
import { activateAccountStorage } from './accountStorage';
import { offlineDownloadService } from './offlineDownloadService';
import { chapterService } from './chapterService';
import { offlineReaderStore, chapterAudioStore } from './offlineReaderStore';
import { offlineTranslations } from './offlineTranslations';
import { audioService } from './audioService';
import apiClient from './apiClient';
import type { OfflineManifestPage } from '../generated/api';
vi.mock('./apiClient', () => ({ default: { get: vi.fn() } }));
vi.mock('./chapterService', () => ({ chapterService: { getReadingProgress: vi.fn(), getChapterContentByNumber: vi.fn() } }));
vi.mock('./offlineReaderStore', () => ({ offlineReaderStore: { save: vi.fn() }, chapterAudioStore: { save: vi.fn() } }));
vi.mock('./offlineLibraryStore', () => ({ offlineLibraryStore: { budget: vi.fn(async () => ({ total_bytes: 0, limit_bytes: 10_000, remaining_bytes: 10_000 })) } }));
vi.mock('./offlineTranslations', () => ({ offlineTranslations: { save: vi.fn() } }));
vi.mock('./audioService', () => ({ audioService: { audio: vi.fn(), manifest: vi.fn() } }));
const document = { schema_version: 1 as const, source_format: 'html' as const, content_version: 'current', plain_text: 'A story.', blocks: [{ id: 'p1', kind: 'p', html: '<p>A story.</p>', text: 'A story.' }] };
const page: OfflineManifestPage = { ...identity(42,3),novel_id: 42, library_id: 1, novel_title: 'Story', total: 1, offset: 0, limit: 200, chapters: [{ ...identity(42,3),id: 3, chapter_number: 3, title: 'Chapter', downloaded: true, source_version: 'current', text_bytes_estimate: 300, audio: { job_id: 8, bytes: 10, source_version: 'current' }, translations: [{ job_id: 9, language: 'de', bytes_estimate: 100, source_version: 'current' }], translations_limited: false }] };
beforeEach(() => {
  vi.clearAllMocks(); activateAccountStorage(1);
  vi.mocked(chapterService.getReadingProgress).mockResolvedValue(null);
  vi.mocked(chapterService.getChapterContentByNumber).mockResolvedValue({ ...identity(42,3),source_version:document.content_version,current_content_version:document.content_version,id: 3, novel_id: 42, chapter_number: 3, title: 'Chapter', content: document.plain_text, document });
  vi.mocked(apiClient.get).mockImplementation(async url => ({ data: url.includes('offline-manifest') ? structuredClone(page) : { ...identity(42,3),id: 9, novel_id: 42, chapter_number: 3, language: 'de', source_version: 'current', status: 'completed', completed_blocks: 1, total_blocks: 1, document, charged_usd: 0 } }));
  vi.mocked(audioService.audio).mockResolvedValue(new Blob(['0123456789']));
  vi.mocked(audioService.manifest).mockResolvedValue({...identity(42,3),job_id: 8, source_version: 'current', rendition: 'original', include_author_notes: false, precision: 'unavailable', duration_seconds: null, segments: [] });
  vi.mocked(offlineReaderStore.save).mockResolvedValue();
});
const plan = () => offlineDownloadService.plan(1, 42, 'all', 0, { audio: true, translations: true }, () => true);

it('previews metadata and known media sizes without downloading or generating content', async () => {
  const review = await plan(); expect(review.estimatedBytes).toBe(410); expect(review.audioCount).toBe(1); expect(review.translationCount).toBe(1);
  expect(chapterService.getChapterContentByNumber).not.toHaveBeenCalled(); expect(audioService.audio).not.toHaveBeenCalled(); expect(offlineReaderStore.save).not.toHaveBeenCalled();
});
it('copies only reviewed completed media with matching original identity', async () => {
  const review = await plan();
  expect(await offlineDownloadService.copy(review, () => true, vi.fn())).toEqual({ text: 1, audio: 1, translations: 1, failed: 0 });
  expect(offlineReaderStore.save).toHaveBeenCalledWith(expect.objectContaining({ library_id: 1, novel_title: 'Story', document }), { pinned: true });
  expect(chapterAudioStore.save).toHaveBeenCalledOnce(); expect(offlineTranslations.save).toHaveBeenCalledOnce();
  expect(vi.mocked(apiClient.get).mock.calls.map(call => call[0])).toEqual(['/reader/stories/42/offline-manifest', '/reader/offline/translations/9']);
});
it('rejects late original content after switching accounts before any write', async () => {
  const review = await plan();
  vi.mocked(chapterService.getChapterContentByNumber).mockImplementation(async () => { activateAccountStorage(2); return { ...identity(42,3),source_version:document.content_version,current_content_version:document.content_version,id: 3, novel_id: 42, chapter_number: 3, title: 'Private A', content: document.plain_text, document }; });
  await expect(offlineDownloadService.copy(review, () => true, vi.fn())).rejects.toMatchObject({ name: 'AbortError' });
  expect(offlineReaderStore.save).not.toHaveBeenCalled(); expect(chapterAudioStore.save).not.toHaveBeenCalled(); expect(offlineTranslations.save).not.toHaveBeenCalled();
});
it('does not save late audio into another account or begin translation afterward', async () => {
  const review = await plan();
  vi.mocked(audioService.audio).mockImplementation(async () => { activateAccountStorage(2); return new Blob(['0123456789']); });
  await expect(offlineDownloadService.copy(review, () => true, vi.fn())).rejects.toMatchObject({ name: 'AbortError' });
  expect(chapterAudioStore.save).not.toHaveBeenCalled(); expect(offlineTranslations.save).not.toHaveBeenCalled();
});
it('preserves previous copies when the source changes or local quota rejects replacement', async () => {
  const review = await plan();
  vi.mocked(chapterService.getChapterContentByNumber).mockResolvedValueOnce({ ...identity(42,3),source_version:document.content_version,current_content_version:document.content_version,id: 3, novel_id: 42, chapter_number: 3, title: 'New', content: 'Changed', document: { ...document, content_version: 'changed' } });
  expect((await offlineDownloadService.copy(review, () => true, vi.fn())).failed).toBe(1); expect(offlineReaderStore.save).not.toHaveBeenCalled();
  vi.mocked(offlineReaderStore.save).mockRejectedValueOnce(new DOMException('Full', 'QuotaExceededError'));
  expect((await offlineDownloadService.copy(review, () => true, vi.fn())).failed).toBe(1); expect(chapterAudioStore.save).not.toHaveBeenCalled();
});
it('stops an unmounted or canceled operation after its in-flight read', async () => {
  const review = await plan(); let active = true;
  vi.mocked(chapterService.getChapterContentByNumber).mockImplementation(async () => { active = false; return { ...identity(42,3),source_version:document.content_version,current_content_version:document.content_version,id: 3, novel_id: 42, chapter_number: 3, title: 'Chapter', content: document.plain_text, document }; });
  await expect(offlineDownloadService.copy(review, () => active, vi.fn())).rejects.toMatchObject({ name: 'AbortError' });
  expect(offlineReaderStore.save).not.toHaveBeenCalled();
});
it('paginates gapped chapters and chooses next chapters from the saved reading position', async () => {
  vi.mocked(chapterService.getReadingProgress).mockResolvedValue({ novel_id: 42, chapter_number: 3, position: 0, percent: 0, revision: 1, updated_at: '2026-10-16T00:00:00Z' });
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { ...page, total: 3, chapters: [{ ...page.chapters[0],...identity(42,1), chapter_number: 1 }] } })
    .mockResolvedValueOnce({ data: { ...page, total: 3, offset: 1, chapters: [{ ...page.chapters[0],...identity(42,3), chapter_number: 3 }, { ...page.chapters[0],...identity(42,7), chapter_number: 7 }] } });
  const review = await offlineDownloadService.plan(1, 42, 'next', 2, { audio: false, translations: false }, () => true);
  expect(review.chapters.map(row => row.chapter_number)).toEqual([3, 7]); expect(review.audioCount).toBe(0);
});
it('can prepare a small next selection without traversing an enormous story', async () => {
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { ...page, total: 100_000 } });
  const review = await offlineDownloadService.plan(1, 42, 'next', 1, { audio: false, translations: false }, () => true);
  expect(review.chapters).toHaveLength(1); expect(apiClient.get).toHaveBeenCalledOnce();
});

it('starts a new reading at negative-numbered prologues and requests followed categories', async () => {
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { ...page, total: 3, chapters: [-2, 0, 3].map(chapter_number => ({ ...page.chapters[0],...identity(42,chapter_number), chapter_number })) } });
  const review = await offlineDownloadService.plan(1, 42, 'next', 2, { audio: false, translations: false }, () => true);
  expect(review.chapters.map(row => row.chapter_number)).toEqual([-2, 0]);
  expect(apiClient.get).toHaveBeenCalledWith('/reader/stories/42/offline-manifest', { params: { offset: 0, limit: 200, followed_only: true, downloaded_only: true } });
});
it('keeps an actual chapter-zero position and skips a finished current chapter', async () => {
  vi.mocked(chapterService.getReadingProgress).mockResolvedValue({ novel_id: 42, chapter_number: 0, position: 0, percent: 95, revision: 1, updated_at: '2026-10-16T00:00:00Z' });
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { ...page, total: 3, chapters: [-2, 0, 7].map(chapter_number => ({ ...page.chapters[0],...identity(42,chapter_number), chapter_number })) } });
  const review = await offlineDownloadService.plan(1, 42, 'next', 2, { audio: false, translations: false }, () => true);
  expect(review.chapters.map(row => row.chapter_number)).toEqual([7]);
  expect(apiClient.get).toHaveBeenCalledWith('/reader/stories/42/offline-manifest', { params: { offset: 0, limit: 200, followed_only: true, downloaded_only: true, from_chapter: 0 } });
});
it('jumps to a late current position before requesting bounded pages', async () => {
  vi.mocked(chapterService.getReadingProgress).mockResolvedValue({ novel_id: 42, chapter_number: 90_000, position: 0, percent: 30, revision: 1, updated_at: '2026-10-16T00:00:00Z' });
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { ...page, total: 10_000, chapters: [{ ...page.chapters[0],...identity(42,90), chapter_number: 90_000 }] } });
  const review = await offlineDownloadService.plan(1, 42, 'next', 1, { audio: false, translations: false }, () => true);
  expect(review.chapters[0].chapter_number).toBe(90_000);
  expect(apiClient.get).toHaveBeenCalledOnce();
  expect(apiClient.get).toHaveBeenCalledWith('/reader/stories/42/offline-manifest', { params: { offset: 0, limit: 200, followed_only: true, downloaded_only: true, from_chapter: 90_000 } });
});

it('rejects a renumbered replacement with identical text before saving any reviewed media', async () => {
  const review = await plan();
  vi.mocked(chapterService.getChapterContentByNumber).mockResolvedValueOnce({ ...identity(42,99),source_version:document.content_version,current_content_version:document.content_version,id: 99, novel_id: 42, chapter_number: 3, title: 'Replacement', content: document.plain_text, document });
  expect(await offlineDownloadService.copy(review, () => true, vi.fn())).toEqual({ text: 0, audio: 0, translations: 0, failed: 1 });
  expect(offlineReaderStore.save).not.toHaveBeenCalled();
  expect(audioService.audio).not.toHaveBeenCalled();
  expect(offlineTranslations.save).not.toHaveBeenCalled();
});
