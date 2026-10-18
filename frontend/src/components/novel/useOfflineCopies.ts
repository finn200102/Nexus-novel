import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { offlineReaderStore, type OfflineChapterSummary } from '../../services/offlineReaderStore';
import { storageGeneration, onAccountStorageChange } from '../../services/accountStorage';
import { offlineDownloadService, type OfflineCopyOptions, type OfflineCopyPlan } from '../../services/offlineDownloadService';

export const formatBytes = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
export interface OfflineCopies {
  stored: OfflineChapterSummary[]; totalBytes: number; progress: { done: number; total: number } | null;
  message: string | null; busy: boolean; review: OfflineCopyPlan | null;
  saveBatch: (wanted: 'next' | 'all', count: number) => Promise<void>;
  reviewBatch: (wanted: 'next' | 'all', count: number, options: OfflineCopyOptions) => Promise<void>;
  confirmBatch: () => Promise<void>; cancelBatch: () => void; removeAll: () => Promise<void>;
}

/** Explicit local copies use the same source/version and account fences as reading. */
export function useOfflineCopies(libraryId: number, novelId: number): OfflineCopies {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  const [stored, setStored] = useState<OfflineChapterSummary[]>([]), [review, setReview] = useState<OfflineCopyPlan | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null), [message, setMessage] = useState<string | null>(null);
  const mounted = useRef(false), operation = useRef(0), locked = useRef(false);
  const refresh = useCallback(async () => {
    const token = operation.current;
    const rows = await offlineReaderStore.listForNovel(novelId);
    if (mounted.current && generation === storageGeneration() && token === operation.current) setStored(rows);
  }, [novelId, generation]);
  useEffect(() => {
    const invalidate = () => { operation.current++; };
    mounted.current = true; operation.current++; locked.current = false; setStored([]); setProgress(null); setReview(null); setMessage(null);
    const token = operation.current;
    if (novelId) void refresh().catch(() => { if (mounted.current && generation === storageGeneration() && token === operation.current) setMessage('Could not open offline storage.'); });
    return () => { mounted.current = false; invalidate(); };
  }, [libraryId, novelId, generation, refresh]);
  const execute = async (plan: OfflineCopyPlan, current: () => boolean) => {
    const result = await offlineDownloadService.copy(plan, current, (done, total) => { if (current()) setProgress({ done, total }); });
    if (!current()) return;
    const parts = [`Saved ${result.text} chapter${result.text === 1 ? '' : 's'} offline.`];
    if (plan.options.audio) parts.push(`${result.audio} recordings saved.`);
    if (plan.options.translations) parts.push(`${result.translations} translations saved.`);
    if (result.failed) parts.push(`${result.failed} items could not be saved. Existing copies are preserved; check storage and review changed content.`);
    if (plan.unavailable) parts.push(`${plan.unavailable} chapters not downloaded on Nexus yet.`);
    if (plan.unknownVersion) parts.push(`${plan.unknownVersion} source versions could not be checked.`);
    setMessage(parts.join(' '));
    await refresh().catch(() => { if (current()) setMessage(`${parts.join(' ')} Could not refresh the local chapter list.`); });
  };
  const work = async (wanted: 'next' | 'all', count: number, options: OfflineCopyOptions, onlyReview: boolean) => {
    if (locked.current || !mounted.current || !novelId || generation !== storageGeneration()) return;
    const token = ++operation.current, current = () => mounted.current && generation === storageGeneration() && token === operation.current;
    locked.current = true; setMessage(null); setReview(null); setProgress({ done: 0, total: 0 });
    try {
      const plan = await offlineDownloadService.plan(libraryId, novelId, wanted, count, options, current);
      if (!current()) return;
      if (onlyReview) {
        setReview(plan);
        await refresh().catch(() => { if (current()) setMessage('Offline review is ready. Could not refresh the existing local chapter count.'); });
      }
      else await execute(plan, current);
    } catch { if (current()) setMessage('Could not prepare offline copies. Check your connection and local storage, then review again.'); }
    finally { if (current()) { locked.current = false; setProgress(null); } }
  };
  const cancelBatch = () => { operation.current++; locked.current = false; setProgress(null); setReview(null); setMessage('Offline copying stopped. Completed copies are retained.'); };
  const confirmBatch = async () => {
    if (!review || locked.current || review.generation !== storageGeneration()) return;
    const plan = review, token = ++operation.current, current = () => mounted.current && generation === storageGeneration() && token === operation.current;
    locked.current = true; setReview(null); setProgress({ done: 0, total: plan.chapters.length });
    try { await execute(plan, current); }
    catch { if (current()) setMessage('Offline copying stopped. Completed copies are retained.'); }
    finally { if (current()) { locked.current = false; setProgress(null); } }
  };
  const removeAll = async () => {
    if (locked.current || generation !== storageGeneration()) return;
    const token = ++operation.current, current = () => mounted.current && generation === storageGeneration() && token === operation.current;
    locked.current = true; setProgress({ done: 0, total: 0 });
    try { const removed = await offlineReaderStore.removeForNovel(novelId); if (current()) { setReview(null); setMessage(`Removed ${removed} offline text chapters.`); await refresh(); } }
    catch { if (current()) setMessage('Could not remove offline text.'); }
    finally { if (current()) { locked.current = false; setProgress(null); } }
  };
  return { stored, totalBytes: stored.reduce((sum, row) => sum + row.size_bytes, 0), progress, message, busy: progress !== null,
    review, saveBatch: (wanted, count) => work(wanted, count, { audio: false, translations: false }, false),
    reviewBatch: (wanted, count, options) => work(wanted, count, options, true), confirmBatch, cancelBatch, removeAll };
}
