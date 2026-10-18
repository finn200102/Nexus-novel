import type { ChapterIdentity } from '../../src/services/chapterIdentity';
/** Explicit deterministic mock-server identities, independent from content hash. */
export const fixtureChapterIdentity = (novelId: number, chapterNumber: number, revision = '1'): ChapterIdentity => ({
  chapter_key: `11111111-${novelId.toString(16).padStart(4,'0')}-4111-8111-${(chapterNumber+2147483648).toString(16).padStart(12,'0')}`,
  manifest_epoch: `22222222-${novelId.toString(16).padStart(4,'0')}-4222-8222-222222222222`, manifest_revision: revision,
});
export const fixtureChapterCacheKey = (novelId: number, chapterNumber: number) => `${novelId}:${fixtureChapterIdentity(novelId, chapterNumber).chapter_key}`;
