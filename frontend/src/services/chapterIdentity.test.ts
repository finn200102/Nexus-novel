import { beforeEach, describe, expect, it, vi } from 'vitest';
import { activateAccountStorage, storageGeneration } from './accountStorage';
import { chapterIdentity, chapterSourceVersion, expectedChapterIdentity, chapterManifestFence, compareManifestRevision, observeChapterIdentity, assertCurrentChapterIdentity, ChapterManifestChangedError, CHAPTER_MANIFEST_CHANGED, type ChapterIdentity } from './chapterIdentity';
const first: ChapterIdentity = { chapter_key: '11111111-1111-4111-8111-111111111111', manifest_epoch: '22222222-2222-4222-8222-222222222222', manifest_revision: '1' };
beforeEach(() => { activateAccountStorage(null); activateAccountStorage(117); });
describe('server-issued chapter identity', () => {
  it('requires an immutable key, epoch and exact decimal revision, never a numeric address/hash', () => {
    expect(chapterIdentity({ chapter_number: 0, source_version: 'same-text' })).toBeNull();
    expect(chapterIdentity({ ...first, manifest_revision: 1 })).toBeNull();
    expect(chapterIdentity({ ...first, manifest_revision: '01' })).toBeNull();
    expect(chapterIdentity({ ...first, manifest_revision: '9223372036854775807' })).toEqual({ ...first, manifest_revision: '9223372036854775807' });
    expect(expectedChapterIdentity(first, 'original-version')).toEqual({ expected_chapter_key: first.chapter_key, expected_manifest_epoch: first.manifest_epoch, expected_manifest_revision: '1', expected_content_version: 'original-version' });
  });
  it('distinguishes a displayed historical body from the current original without hashing or inventing versions',()=>{
    const historical={source_version:'displayed-old',current_content_version:'current-original',document:{content_version:'displayed-old'}};
    expect(chapterSourceVersion(historical)).toBe('displayed-old');expect(chapterSourceVersion(historical,true)).toBe('current-original');
    expect(chapterSourceVersion({content:'Legacy plaintext',source_version:'server-plain-hash'},true)).toBe('server-plain-hash');
    expect(chapterSourceVersion({content:'Unversioned plaintext'},true)).toBeUndefined();
  });
  it('compares revisions past the JavaScript safe-integer boundary without rounding', () => {
    expect(compareManifestRevision('9007199254740992', '9007199254740993')).toBe(-1);
    expect(compareManifestRevision('10', '9')).toBe(1);
  });
  it('fences old async responses and captured writes after a topology change, with an explicit event', () => {
    const listener = vi.fn(); window.addEventListener(CHAPTER_MANIFEST_CHANGED, listener);
    const generation = storageGeneration(); observeChapterIdentity(42, first, generation);
    observeChapterIdentity(42, { ...first, manifest_revision: '2' }, generation);
    expect(listener).toHaveBeenCalledOnce();
    expect(() => assertCurrentChapterIdentity(42, first)).toThrow(ChapterManifestChangedError);
    expect(() => observeChapterIdentity(42, first, generation)).toThrow(ChapterManifestChangedError);
    window.removeEventListener(CHAPTER_MANIFEST_CHANGED, listener);
  });
  it('rejects a late first observation after another request established a different lifecycle', () => {
    const fence = chapterManifestFence(42), generation = storageGeneration();
    observeChapterIdentity(42, first, generation, fence);
    expect(() => observeChapterIdentity(42, { ...first, manifest_epoch: '33333333-3333-4333-8333-333333333333' }, generation, fence)).toThrow(ChapterManifestChangedError);
  });
  it('does not let a late old epoch replace a new story lifecycle or cross an account', () => {
    const generation = storageGeneration(); observeChapterIdentity(42, first, generation);
    const replacement = { ...first, manifest_epoch: '33333333-3333-4333-8333-333333333333' };
    observeChapterIdentity(42, replacement, generation);
    expect(() => observeChapterIdentity(42, first, generation)).toThrow(ChapterManifestChangedError);
    activateAccountStorage(118);
    expect(() => observeChapterIdentity(42, first, generation)).toThrow('Reading account changed');
    expect(() => observeChapterIdentity(42, first, storageGeneration())).not.toThrow();
  });
});

it('requires review before replacing an unbound older place at a reused numeric address',async()=>{const {savedChapterPlaceNeedsReview}=await import('./chapterIdentity');const loaded={chapter_number:0,chapter_key:'11111111-1111-4111-8111-111111111111',manifest_epoch:'22222222-2222-4222-8222-222222222222',manifest_revision:'2'};expect(savedChapterPlaceNeedsReview({chapter_number:0,percent:40},loaded)).toBe(true);expect(savedChapterPlaceNeedsReview({chapter_number:0,chapter_key:'33333333-3333-4333-8333-333333333333',block_id:'old-anchor'},loaded)).toBe(true);expect(savedChapterPlaceNeedsReview({chapter_number:-2,percent:40},loaded)).toBe(false);expect(savedChapterPlaceNeedsReview({chapter_number:0,chapter_key:loaded.chapter_key,percent:40},loaded)).toBe(false);});
