import { chapterIdentity, assertCurrentChapterIdentity, compareManifestRevision, ChapterManifestChangedError, type ChapterIdentity } from './chapterIdentity';
import { OFFLINE_METADATA } from './offlineStorageDatabase';

export const stableOfflineChapterKey = (novelId: number, identity: ChapterIdentity) => `${novelId}:${identity.chapter_key}`;
const manifestKey = (novelId: number) => `chapter-manifest:${novelId}`;
const addressKey = (novelId: number, chapterNumber: number) => `chapter-address:${novelId}:${chapterNumber}`;
/** Called inside the payload transaction: an old tab cannot republish an old
 * numeric address after another transaction observed a newer topology. */
export function registerOfflineChapterIdentity(tx: IDBTransaction, novelId: number, chapterNumber: number, identity: ChapterIdentity, done: () => void): void {
  if (!chapterIdentity(identity) || !Number.isSafeInteger(chapterNumber)) throw new ChapterManifestChangedError();
  assertCurrentChapterIdentity(novelId, identity);
  const metadata = tx.objectStore(OFFLINE_METADATA), request = metadata.get(manifestKey(novelId));
  request.onsuccess = () => {
    try {
      assertCurrentChapterIdentity(novelId, identity);
      const previous = request.result as (ChapterIdentity & { retired_epochs?: string[] }) | undefined;
      if (previous?.retired_epochs?.includes(identity.manifest_epoch)
          || previous?.manifest_epoch === identity.manifest_epoch && compareManifestRevision(identity.manifest_revision, previous.manifest_revision) < 0) throw new ChapterManifestChangedError();
      const retired = [...new Set([...(previous?.retired_epochs ?? []), ...(previous && previous.manifest_epoch !== identity.manifest_epoch ? [previous.manifest_epoch] : [])])];
      const reverseKey=`chapter-key:${novelId}:${identity.chapter_key}`,reverse=metadata.get(reverseKey);
      reverse.onsuccess=()=>{
        try{
          const bound=reverse.result;
          if(bound && bound.manifest_epoch===identity.manifest_epoch && bound.manifest_revision===identity.manifest_revision && bound.chapter_number!==chapterNumber)throw new ChapterManifestChangedError();
          metadata.put({ key: manifestKey(novelId), ...identity, retired_epochs: retired });
          metadata.put({ key: addressKey(novelId, chapterNumber), ...identity });
          metadata.put({ key: reverseKey, ...identity, chapter_number:chapterNumber });
          done();
        }catch(error){failOfflineIdentity(tx,error);}
      };
    } catch (error) { failOfflineIdentity(tx, error); }
  };
}
const failures = new WeakMap<IDBTransaction, unknown>();
export const offlineIdentityFailure = (tx: IDBTransaction) => failures.get(tx);
export function failOfflineIdentity(tx: IDBTransaction, error: unknown) { failures.set(tx, error); try { tx.abort(); } catch { /* Already finished. */ } }
/** A route number can resolve only within the last verified mapping. Payload
 * keys remain immutable UUIDs; old aliases are ignored after a revision change. */
export function resolveOfflineChapterIdentity(tx: IDBTransaction, novelId: number, chapterNumber: number, done: (identity: ChapterIdentity | null) => void, expected?: ChapterIdentity): void {
  const metadata = tx.objectStore(OFFLINE_METADATA), address = metadata.get(addressKey(novelId, chapterNumber));
  address.onsuccess = () => {
    const identity = chapterIdentity(address.result);
    if (!identity) { done(null); return; }
    const manifest = metadata.get(manifestKey(novelId));
    manifest.onsuccess = () => {
      const current = manifest.result;
      if (!current || current.manifest_epoch !== identity.manifest_epoch || current.manifest_revision !== identity.manifest_revision
          || expected && (expected.chapter_key !== identity.chapter_key || expected.manifest_epoch !== identity.manifest_epoch || expected.manifest_revision !== identity.manifest_revision)) { done(null); return; }
      try { assertCurrentChapterIdentity(novelId, identity); done(identity); } catch { done(null); }
    };
  };
}
