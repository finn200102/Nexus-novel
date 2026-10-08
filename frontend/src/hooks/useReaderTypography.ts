import { useCallback, useEffect, useState } from "react";
import {
  readGlobalTypography,
  readStoryOverride,
  resolveTypography,
  ReaderTypography,
  writeGlobalTypography,
  writeStoryOverride,
} from "../components/reader/readerSettings";

type Setter<K extends keyof ReaderTypography> =
  | ReaderTypography[K]
  | ((current: ReaderTypography[K]) => ReaderTypography[K]);

/**
 * Reader typography with a per-story layer. By default changes are saved globally;
 * with "Only for this story" on, they go to a snapshot for this story so later
 * global changes don't leak into it.
 */
export function useReaderTypography(novelId: number) {
  const [global, setGlobal] = useState<ReaderTypography>(readGlobalTypography);
  const [override, setOverride] = useState(() => readStoryOverride(novelId));
  const [loadedFor, setLoadedFor] = useState(novelId);

  if (loadedFor !== novelId) {
    // Story changed: load its override during render so effects see the right pair.
    setLoadedFor(novelId);
    setOverride(readStoryOverride(novelId));
  }

  useEffect(() => { writeGlobalTypography(global); }, [global]);
  useEffect(() => { writeStoryOverride(novelId, override); }, [novelId, override]);

  const typography = resolveTypography(global, override);
  const storyOnly = override !== null;

  const set = useCallback(<K extends keyof ReaderTypography>(key: K, value: Setter<K>) => {
    const apply = (current: ReaderTypography): ReaderTypography => {
      const next = typeof value === "function" ? (value as (c: ReaderTypography[K]) => ReaderTypography[K])(current[key]) : value;
      return { ...current, [key]: next };
    };
    if (storyOnly) setOverride((prev) => apply(resolveTypography(global, prev)));
    else setGlobal((prev) => apply(prev));
  }, [global, storyOnly]);

  /** Switch "Only for this story": on snapshots the current values, off returns to the global ones. */
  const setStoryOnly = useCallback((value: boolean) => {
    setOverride((prev) => (value ? resolveTypography(global, prev) : null));
  }, [global]);

  const useForAllStories = useCallback(() => {
    setGlobal(resolveTypography(global, override));
    setOverride(null);
  }, [global, override]);

  return {
    typography,
    set,
    storyOnly,
    setStoryOnly,
    useForAllStories,
    /** Kept for callers of the 1.0 API. */
    hasStoryOverride: storyOnly,
    resetToGlobal: useCallback(() => setOverride(null), []),
  };
}
