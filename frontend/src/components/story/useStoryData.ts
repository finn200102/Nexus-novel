import axios from "axios";
import { useCallback, useEffect, useState } from "react";
import { discoveryService } from "../../services/discoveryService";
import { novelService } from "../../services/novelService";
import { storyService, type LibraryEntry } from "../../services/storyService";
import type { SupportLink } from "../../lib/supportLinks";
import type { DiscoveredNovel } from "../../types/discovery";
import type { Novel, NovelFollowSettings } from "../../types/novel";

export interface LibraryCopyRef {
  libraryId: number;
  novelId: number;
}

export interface StoryData {
  loading: boolean;
  /** Nothing could be loaded: neither a catalog record nor a library copy. */
  notFound: boolean;
  /** The story is outside the content limits of this profile (the API answered 403). */
  restricted: boolean;
  catalog: DiscoveredNovel | null;
  entries: LibraryEntry[];
  /** Author support links from the catalog story (validated by the API). */
  supportLinks: SupportLink[];
  /** The library copy shown on the page, if any. */
  copy: LibraryCopyRef | null;
  novel: Novel | null;
  followSettings: NovelFollowSettings | null;
  setNovel: (novel: Novel) => void;
  setFollowSettings: (settings: NovelFollowSettings) => void;
  reload: () => Promise<void>;
}

/**
 * Loads a story by catalog id: the catalog record, the user's library copies, and the chosen
 * copy's library data. `preferredCopy` picks among several copies (from `?copy=`); `fallbackCopy`
 * serves library stories that have no catalog id yet.
 */
const isForbidden = (reason: unknown) => axios.isAxiosError(reason) && reason.response?.status === 403;

export function useStoryData(metadataId: number | null, preferredCopy: number | null, fallbackCopy: LibraryCopyRef | null = null): StoryData {
  const [loading, setLoading] = useState(true);
  const [restricted, setRestricted] = useState(false);
  const [catalog, setCatalog] = useState<DiscoveredNovel | null>(null);
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [supportLinks, setSupportLinks] = useState<SupportLink[]>([]);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [followSettings, setFollowSettings] = useState<NovelFollowSettings | null>(null);
  const [copy, setCopy] = useState<LibraryCopyRef | null>(null);
  const fallbackLibrary = fallbackCopy?.libraryId ?? null;
  const fallbackNovel = fallbackCopy?.novelId ?? null;

  const load = useCallback(async (isActive: () => boolean = () => true) => {
    setLoading(true);
    let nextCatalog: DiscoveredNovel | null = null;
    let nextEntries: LibraryEntry[] = [];
    let nextSupport: SupportLink[] = [];
    let nextRestricted = false;
    if (metadataId) {
      const [catalogResult, membershipResult] = await Promise.allSettled([
        discoveryService.getNovelById(metadataId),
        storyService.membership(metadataId),
      ]);
      if (catalogResult.status === "fulfilled" && catalogResult.value && "id" in catalogResult.value) nextCatalog = catalogResult.value;
      if (catalogResult.status === "rejected" && isForbidden(catalogResult.reason)) nextRestricted = true;
      if (membershipResult.status === "fulfilled") {
        nextEntries = membershipResult.value.library_entries;
        nextSupport = membershipResult.value.support_links;
      }
    }
    const chosen = nextEntries.find((entry) => entry.novel_id === preferredCopy) ?? nextEntries[0];
    const nextCopy = chosen
      ? { libraryId: chosen.library_id, novelId: chosen.novel_id }
      : fallbackLibrary && fallbackNovel
        ? { libraryId: fallbackLibrary, novelId: fallbackNovel }
        : null;

    let nextNovel: Novel | null = null;
    let nextSettings: NovelFollowSettings | null = null;
    if (nextCopy) {
      const [novelResult, settingsResult] = await Promise.allSettled([
        novelService.getNovelById(nextCopy.libraryId, nextCopy.novelId),
        novelService.getFollowSettings(nextCopy.libraryId, nextCopy.novelId),
      ]);
      if (novelResult.status === "fulfilled" && novelResult.value && "id" in novelResult.value) nextNovel = novelResult.value as Novel;
      if (novelResult.status === "rejected" && isForbidden(novelResult.reason)) nextRestricted = true;
      if (settingsResult.status === "fulfilled") nextSettings = settingsResult.value;
    }
    if (!isActive()) return;
    if (nextRestricted) {
      nextCatalog = null;
      nextNovel = null;
    }
    setRestricted(nextRestricted);
    setCatalog(nextCatalog);
    setEntries(nextEntries);
    setSupportLinks(nextSupport);
    setCopy(nextNovel ? nextCopy : null);
    setNovel(nextNovel);
    setFollowSettings(nextSettings);
    setLoading(false);
  }, [metadataId, preferredCopy, fallbackLibrary, fallbackNovel]);

  useEffect(() => {
    let active = true;
    void load(() => active);
    return () => {
      active = false;
    };
  }, [load]);

  return {
    loading,
    notFound: !loading && !catalog && !novel,
    restricted: !loading && restricted,
    catalog,
    entries,
    supportLinks,
    copy,
    novel,
    followSettings,
    setNovel,
    setFollowSettings,
    reload: useCallback(() => load(), [load]),
  };
}
