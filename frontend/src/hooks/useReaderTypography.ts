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
 * Typography with a per-story layer. Changing a value while reading creates a
 * story override (a full snapshot, so later global changes don't leak into it).
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

  const setField = useCallback(<K extends keyof ReaderTypography>(key: K, value: Setter<K>) => {
    setOverride((prev) => {
      const current = resolveTypography(global, prev);
      const next = typeof value === "function" ? (value as (c: ReaderTypography[K]) => ReaderTypography[K])(current[key]) : value;
      return { ...current, [key]: next };
    });
  }, [global]);

  const useForAllStories = useCallback(() => {
    setGlobal(resolveTypography(global, override));
    setOverride(null);
  }, [global, override]);

  const resetToGlobal = useCallback(() => setOverride(null), []);

  return {
    typography,
    setFontScale: useCallback((value: Setter<"fontScale">) => setField("fontScale", value), [setField]),
    setLineHeight: useCallback((value: Setter<"lineHeight">) => setField("lineHeight", value), [setField]),
    setContentWidth: useCallback((value: Setter<"contentWidth">) => setField("contentWidth", value), [setField]),
    setTheme: useCallback((value: Setter<"theme">) => setField("theme", value), [setField]),
    hasStoryOverride: override !== null,
    useForAllStories,
    resetToGlobal,
  };
}
