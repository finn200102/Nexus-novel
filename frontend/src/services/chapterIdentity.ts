import { onAccountStorageChange, storageGeneration } from './accountStorage';

/** A chapter number is an address. These server-issued fields identify the work
 * at that address; never manufacture them from a number or a content hash. */
export type ChapterIdentity=Pick<import('../generated/api').Chapter,'chapter_key'|'manifest_epoch'|'manifest_revision'>;
export interface ExpectedChapterIdentity {
  expected_chapter_key: string;
  expected_manifest_epoch: string;
  expected_manifest_revision: string;
  expected_content_version?: string;
}
export const CHAPTER_MANIFEST_CHANGED = 'nexus-chapter-manifest-changed';
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function chapterIdentity(value: unknown): ChapterIdentity | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  return typeof row.chapter_key === 'string' && uuid.test(row.chapter_key)
    && typeof row.manifest_epoch === 'string' && uuid.test(row.manifest_epoch)
    && typeof row.manifest_revision === 'string' && /^(0|[1-9]\d{0,18})$/.test(row.manifest_revision)
    ? { chapter_key: row.chapter_key, manifest_epoch: row.manifest_epoch, manifest_revision: row.manifest_revision } : null;
}
export const sameChapterIdentity = (left: ChapterIdentity, right: ChapterIdentity) => left.chapter_key === right.chapter_key
  && left.manifest_epoch === right.manifest_epoch && left.manifest_revision === right.manifest_revision;
export const expectedChapterIdentity = (identity: ChapterIdentity, sourceVersion?: string): ExpectedChapterIdentity => ({
  expected_chapter_key: identity.chapter_key, expected_manifest_epoch: identity.manifest_epoch,
  expected_manifest_revision: identity.manifest_revision, ...(sourceVersion ? { expected_content_version: sourceVersion } : {}),
});
export function compareManifestRevision(left: string, right: string): number {
  return left.length === right.length ? (left === right ? 0 : left < right ? -1 : 1) : left.length < right.length ? -1 : 1;
}
export class ChapterManifestChangedError extends Error {
  constructor() { super('The chapter list changed. Open the current story and review your saved place before continuing.'); this.name = 'ChapterManifestChangedError'; }
}
const manifests = new Map<number, { manifest_epoch: string; manifest_revision: string }>();
const retiredEpochs = new Map<number, Set<string>>();
onAccountStorageChange(() => { manifests.clear(); retiredEpochs.clear(); });
export const chapterManifestFence = (novelId: number): string | null => {
  const known = manifests.get(novelId);
  return known ? `${known.manifest_epoch}:${known.manifest_revision}` : null;
};
/** Only live, account-fenced server responses may advance this runtime fence. */
export function observeChapterIdentity(novelId: number, identity: Pick<ChapterIdentity,"manifest_epoch"|"manifest_revision"> & Partial<Pick<ChapterIdentity,"chapter_key">>, generation: number, requestFence?: string | null): void {
  if (generation !== storageGeneration()) throw new DOMException('Reading account changed', 'AbortError');
  const previous = manifests.get(novelId);
  if (requestFence !== undefined && requestFence !== chapterManifestFence(novelId) && previous
      && (previous.manifest_epoch !== identity.manifest_epoch || previous.manifest_revision !== identity.manifest_revision)) throw new ChapterManifestChangedError();
  if (retiredEpochs.get(novelId)?.has(identity.manifest_epoch)) throw new ChapterManifestChangedError();
  if (previous?.manifest_epoch === identity.manifest_epoch && compareManifestRevision(identity.manifest_revision, previous.manifest_revision) < 0) throw new ChapterManifestChangedError();
  if (previous && (previous.manifest_epoch !== identity.manifest_epoch || previous.manifest_revision !== identity.manifest_revision)) {
    if (previous.manifest_epoch !== identity.manifest_epoch) {
      const retired = retiredEpochs.get(novelId) ?? new Set<string>();
      retired.add(previous.manifest_epoch); retiredEpochs.set(novelId, retired);
    }
    manifests.set(novelId, identity);
    window.dispatchEvent(new CustomEvent(CHAPTER_MANIFEST_CHANGED, { detail: { novelId, ...identity } }));
  } else manifests.set(novelId, identity);
}
export function assertCurrentChapterIdentity(novelId: number, identity: ChapterIdentity): void {
  const known = manifests.get(novelId);
  if (known && (known.manifest_epoch !== identity.manifest_epoch || known.manifest_revision !== identity.manifest_revision)) throw new ChapterManifestChangedError();
}

/** Historical responses identify both the displayed text and the current
 * original. A locator may refer to the former; write preconditions use the latter. */
export function chapterSourceVersion(value: unknown, current = false): string | undefined {
  if (!value || typeof value !== 'object') return;
  const row=value as {source_version?:unknown;current_content_version?:unknown;document?:{content_version?:unknown}};
  const version=current && typeof row.current_content_version==='string' ? row.current_content_version
    : typeof row.source_version==='string' ? row.source_version : row.document?.content_version;
  return typeof version==='string' && version ? version : undefined;
}
/** An unbound old locator must not be silently replaced by an automatic save
 * merely because the same numeric address still exists. */
export function savedChapterPlaceNeedsReview(saved:{chapter_number?:number|null;chapter_key?:string|null;position?:number;percent?:number;block_id?:string|null;text_quote?:string|null}|null|undefined,loaded:{chapter_number:number}&Partial<ChapterIdentity>):boolean {
 const identity=chapterIdentity(loaded);
 return Boolean(identity && saved && saved.chapter_number===loaded.chapter_number && saved.chapter_key!==identity.chapter_key
  && ((saved.position??0)>0||(saved.percent??0)>0||saved.block_id||saved.text_quote));
}
