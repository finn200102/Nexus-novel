import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { chapterService, type ChapterReadingSummary } from "../services/chapterService";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";
import { getUserFacingError } from "../services/apiClient";
/** Current server facts, scoped to this account and story; never derive counts from a label. */
export function useChapterReadingSummary(novelId: number | null) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration), scope = `${generation}:${novelId}`;
  const mounted = useRef(false), request = useRef(0);
  const [state, setState] = useState<{ scope: string; summary: ChapterReadingSummary | null; loading: boolean; error: string }>({ scope: "", summary: null, loading: false, error: "" });
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const adopt = useCallback((summary: ChapterReadingSummary) => {
    if (!mounted.current || generation !== storageGeneration() || summary.novel_id !== novelId) return;
    setState(previous => previous.scope === scope && (previous.summary?.revision ?? -1) > summary.revision ? previous : { scope, summary, loading: false, error: "" });
  }, [scope, novelId, generation]);
  const refresh = useCallback(async () => {
    if (novelId === null) return null;
    const version = ++request.current;
    setState(previous => ({ scope, summary: previous.scope === scope ? previous.summary : null, loading: true, error: "" }));
    try {
      const summary = await chapterService.getReadingSummary(novelId);
      if (!mounted.current || generation !== storageGeneration() || version !== request.current) return null;
      if (summary.novel_id !== novelId) throw new Error("Invalid reading summary");
      adopt(summary); return summary;
    } catch (error) {
      if (mounted.current && generation === storageGeneration() && version === request.current) setState(previous => ({ scope, summary: previous.scope === scope ? previous.summary : null, loading: false, error: getUserFacingError(error, "Could not refresh chapter records. Counts are not available until they can be verified.") }));
      return null;
    }
  }, [novelId, generation, scope, adopt]);
  useEffect(() => { if (novelId !== null) void refresh(); return () => { request.current += 1; }; }, [novelId, refresh]);
  return { summary: state.scope === scope ? state.summary : null, loading: novelId !== null && (state.scope !== scope || state.loading), error: state.scope === scope ? state.error : "", refresh, adopt };
}
