import { useEffect, useRef, useSyncExternalStore } from "react";
import { readingStatsService } from "../services/readingStatsService";
import { createReadingHeartbeat, HEARTBEAT_INTERVAL_MS } from "../services/readingHeartbeat";
import { readingActivityService } from "../services/readingActivityService";
import { storageGeneration } from "../services/accountStorage";

/** Reports reading time for the open chapter. Scroll events are captured on window, so any scroller counts. */
export function useReadingHeartbeat(novelId: number, chapterId: number | undefined) {
  const state = useSyncExternalStore(readingActivityService.subscribe, readingActivityService.snapshot);
  const chapterAccount = useRef({ novelId, chapterId, generation: storageGeneration() });
  if (chapterAccount.current.novelId !== novelId || chapterAccount.current.chapterId !== chapterId) {
    chapterAccount.current = { novelId, chapterId, generation: storageGeneration() };
  }
  const enabled = chapterAccount.current.generation === state.generation && readingActivityService.canTrack();
  useEffect(() => {
    void readingActivityService.load();
    const refresh = () => { if (document.visibilityState === "visible") void readingActivityService.load(); };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => { window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [state.generation]);
  useEffect(() => {
    if (!chapterId || !enabled) return;
    const generation = storageGeneration();
    const beat = createReadingHeartbeat((seconds, words) =>
      generation === storageGeneration() && readingActivityService.canTrack()
        ? readingStatsService.recordReadingTime(novelId, chapterId, seconds, words)
        : Promise.resolve()
    );
    const mark = () => beat.activity();
    window.addEventListener("scroll", mark, { capture: true, passive: true });
    window.addEventListener("keydown", mark);
    window.addEventListener("pointerdown", mark);
    const interval = window.setInterval(() => beat.tick(), HEARTBEAT_INTERVAL_MS);
    return () => {
      window.removeEventListener("scroll", mark, { capture: true });
      window.removeEventListener("keydown", mark);
      window.removeEventListener("pointerdown", mark);
      window.clearInterval(interval);
    };
  }, [novelId, chapterId, enabled, state.generation]);
}
