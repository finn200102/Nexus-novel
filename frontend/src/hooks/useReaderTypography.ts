import { useCallback, useEffect, useRef, useState } from "react";
import { flushPreferenceScope, installReaderPreferenceSync, queuePreferencePatch, resolvePreferenceConflict, type PreferenceSyncStatus } from "../services/readerPreferenceSync";
import { accountStorage, storageGeneration } from "../services/accountStorage";
import {
  readGlobalTypography,
  readStoryOverride,
  resolveTypography,
  ReaderTypography,
  writeGlobalTypography,
  writeStoryOverride,
  GLOBAL_KEY, READER_DEFAULTS, sanitizeTypography, readLayout, readAuthorNotesMode, readShortcutsEnabled,
  writeLayout, writeAuthorNotesMode, writeShortcutsEnabled,
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
  const [sync, setSync] = useState<PreferenceSyncStatus>({ pending: 0, conflicts: [] });
  const skipGlobal = useRef(JSON.stringify(global));
  const skipStory = useRef(JSON.stringify(override));
  const storedGlobal = useRef((() => { try { return accountStorage.getItem(GLOBAL_KEY) !== null; } catch { return false; } })());

  if (loadedFor !== novelId) {
    // Story changed: load its override during render so effects see the right pair.
    setLoadedFor(novelId);
    const next = readStoryOverride(novelId);
    skipStory.current = JSON.stringify(next);
    setOverride(next);
  }

  useEffect(() => installReaderPreferenceSync(novelId, {
    global: { typography: readGlobalTypography(), layout: readLayout(), authorNotes: readAuthorNotesMode(), shortcuts: readShortcutsEnabled() },
    story: { typography: readStoryOverride(novelId) },
    publishLocal: { global: storedGlobal.current, story: readStoryOverride(novelId) !== null },
  }, (scope, values) => {
    window.dispatchEvent(new Event("nexus-reader-before-style-change"));
    if (scope === "global") {
      const next = { ...READER_DEFAULTS, ...sanitizeTypography(values.typography || {}) };
      skipGlobal.current = JSON.stringify(next);
      writeGlobalTypography(next);
      setGlobal(next);
      writeLayout(values.layout || "scroll", false);
      writeAuthorNotesMode(values.authorNotes || "collapsed", false);
      writeShortcutsEnabled(values.shortcuts ?? true, false);
      window.dispatchEvent(new Event("nexus-reader-preferences-loaded"));
    } else {
      const next = values.typography ? sanitizeTypography(values.typography) : null;
      skipStory.current = JSON.stringify(next);
      writeStoryOverride(novelId, next);
      setOverride(next);
    }
  }, setSync), [novelId]);

  useEffect(() => {
    writeGlobalTypography(global);
    const key = JSON.stringify(global);
    if (skipGlobal.current === key) { skipGlobal.current = ""; return; }
    queuePreferencePatch("global", { typography: global });
    void flushPreferenceScope("global");
  }, [global]);
  useEffect(() => {
    writeStoryOverride(novelId, override);
    const key = JSON.stringify(override);
    if (skipStory.current === key) { skipStory.current = ""; return; }
    const scope = `story:${novelId}` as const;
    queuePreferencePatch(scope, { typography: override });
    void flushPreferenceScope(scope);
  }, [novelId, override]);

  const typography = resolveTypography(global, override);
  const storyOnly = override !== null;

  const set = useCallback(<K extends keyof ReaderTypography>(key: K, value: Setter<K>) => {
    window.dispatchEvent(new Event("nexus-reader-before-style-change"));
    const apply = (current: ReaderTypography): ReaderTypography => {
      const next = typeof value === "function" ? (value as (c: ReaderTypography[K]) => ReaderTypography[K])(current[key]) : value;
      return { ...current, [key]: next };
    };
    if (storyOnly) setOverride((prev) => apply(resolveTypography(global, prev)));
    else setGlobal((prev) => apply(prev));
  }, [global, storyOnly]);

  /** Switch "Only for this story": on snapshots the current values, off returns to the global ones. */
  const setStoryOnly = useCallback((value: boolean) => {
    window.dispatchEvent(new Event("nexus-reader-before-style-change"));
    setOverride((prev) => (value ? resolveTypography(global, prev) : null));
  }, [global]);

  const useForAllStories = useCallback(() => {
    window.dispatchEvent(new Event("nexus-reader-before-style-change"));
    setGlobal(resolveTypography(global, override));
    setOverride(null);
  }, [global, override]);

  return {
    typography,
    set,
    storyOnly,
    setStoryOnly,
    useForAllStories,
    sync,
    resolveSync: async (choice: "account" | "device") => {
      const owner = storageGeneration();
      for (const scope of sync.conflicts) {
        if (owner !== storageGeneration()) break;
        await resolvePreferenceConflict(scope, choice);
      }
    },
    /** Kept for callers of the 1.0 API. */
    hasStoryOverride: storyOnly,
    resetToGlobal: useCallback(() => { window.dispatchEvent(new Event("nexus-reader-before-style-change")); setOverride(null); }, []),
  };
}
