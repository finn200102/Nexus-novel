import { useEffect } from "react";
import { readingStatsService } from "../services/readingStatsService";
import { createReadingHeartbeat, HEARTBEAT_INTERVAL_MS } from "../services/readingHeartbeat";

/** Reports reading time for the open chapter. Scroll events are captured on window, so any scroller counts. */
export function useReadingHeartbeat(novelId: number, chapterId: number | undefined) {
  useEffect(() => {
    if (!chapterId) return;
    const beat = createReadingHeartbeat((seconds, words) =>
      readingStatsService.recordReadingTime(novelId, chapterId, seconds, words)
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
  }, [novelId, chapterId]);
}
