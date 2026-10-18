import {logRequestFailure} from "../services/requestDiagnostics";
import { chapterIdentity, savedChapterPlaceNeedsReview, chapterSourceVersion, expectedChapterIdentity, CHAPTER_MANIFEST_CHANGED, type ChapterIdentity } from "../services/chapterIdentity";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import axios from "axios";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { BookOpenText, Download, FileJson, HardDriveDownload, Keyboard, NotebookPen, Quote, ScrollText, StickyNote, Search } from "lucide-react";
import { chapterService } from "../services/chapterService";
import type { ChapterNavigationResponse } from "../generated/api";
import { isNetworkError } from "../services/networkErrors";
import { chooseChapterNavigation, cacheChapterIndex, cachedChapterIndex, cacheChapterNavigation, cachedChapterNavigation, chapterNeighbors, ChapterIndexLimitError, loadChapterIndex, validNavigation } from "../components/reader/chapterNavigation";
import { novelService } from "../services/novelService";
import { offlineReaderStore } from "../services/offlineReaderStore";
import { getQueuedProgress } from "../services/progressSyncQueue";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";
import { restoreTextLocator, selectedTextLocator, visibleBlockLocator, quoteLocator, type TextLocator, type ChapterDocument } from "../components/reader/chapterDocument";
import ReaderToolsSheet from "../components/reader/ReaderToolsSheet";
import { capturePassage, type PassageAnchor } from "../components/reader/selectedPassage";
import type { TranslationVariant } from "../services/readerToolsService";
import OfflineBadge from "../components/reader/OfflineBadge";
import ChapterBody from "../components/reader/ChapterBody";
import ChapterDrawer from "../components/reader/ChapterDrawer";
import { entryLabel } from "../components/reader/chapterLabels";
import ReaderTopBar from "../components/reader/ReaderTopBar";
import ReaderBottomBar from "../components/reader/ReaderBottomBar";
import ReaderEndOfChapter from "../components/reader/ReaderEndOfChapter";
import ChapterSourceLink from "../components/reader/ChapterSourceLink";
import ReaderSettingsControl from "../components/reader/ReaderSettingsSheet";
import ListenPlayer from "../components/reader/ListenPlayer";
import PreviouslyOn from "../components/reader/PreviouslyOn";
import { AnnotationsSheet, NoteDialog, ReadingAnnotation, RecapData, RecapSheet, ShortcutsDialog } from "../components/reader/ReaderPanels";
import ChapterVersionsSheet from "../components/reader/ChapterVersionsSheet";
import ChapterSearchSheet from "../components/reader/ChapterSearchSheet";
import type { SearchBlock, ChapterMatch } from "../components/reader/chapterSearch";
import { selectChapterMatch } from "../components/reader/chapterSearch";
import { parallelDocument } from "../components/reader/parallelDocument";
import { useReaderAssetsReady } from "../hooks/useReaderAssetsReady";
import {
  AuthorNotesMode,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  readAuthorNotesMode,
  readLayout,
  ReaderLayout,
  readShortcutsEnabled,
  resolveReaderTheme,
  writeAuthorNotesMode,
  writeLayout,
  writeShortcutsEnabled,
} from "../components/reader/readerSettings";
import { typographyStyle } from "../components/reader/typographyStyle";
import { scrollPercent } from "../components/reader/pagedMath";
import { Banner, type MenuItem } from "../components/ui";
import { useReaderPaging } from "../hooks/useReaderPaging";
import { useReadingHeartbeat } from "../hooks/useReadingHeartbeat";
import { useReaderTypography } from "../hooks/useReaderTypography";
import { useReaderShortcuts } from "../hooks/useReaderShortcuts";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { usePageTitle } from "../hooks/usePageTitle";
import { useTheme } from "../theme/useTheme";
import { useToast } from "../context/useToast";
import { displayTitle } from "../utils/displayTitle";
import "../styles/Reader.css";

interface ChapterContent extends Partial<ChapterIdentity> {
  source_version?:string;current_content_version?:string;
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
  source_url?: string | null;
  document?: ChapterDocument;
}

interface Novel {
  id: number;
  title: string;
  author: string;
  novel_site?: string | null;
  library_id: number;
  total_chapters: number;
  next_unread_chapter_id?: number | null;
  next_unread_chapter_number?: number | null;
}

interface ChapterSummary {
  chapter_key?: string;manifest_epoch?:string;manifest_revision?:string;
  id: number;
  chapter_number: number;
  title: string;
  category?: string;
}

interface ReadingProgress {
  chapter_key?: string | null; manifest_epoch?: string | null; manifest_revision?: string | null;
  reading_run_key?: string | null;
  text_quote?: string | null;
  quote_prefix?: string | null;
  quote_suffix?: string | null;
  locator_content_version?: string | null;
  locator_variant?: string | null;
  block_id?: string | null;
  text_offset?: number;
  revision?: number;
  chapter_number?: number | null;
  position: number;
  percent: number;
}

const savedLocator = (value: ReadingProgress | ReadingAnnotation): TextLocator => ({ blockId: value.block_id || undefined,
  textOffset: value.text_offset || 0, textQuote: value.text_quote || undefined,
  quotePrefix: value.quote_prefix || undefined, quoteSuffix: value.quote_suffix || undefined });

const WORDS_PER_MINUTE = 230;

const download = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

const Reader: React.FC = () => {
  const { libraryId, novelId, chapterNumber } = useParams<{
    libraryId: string;
    novelId: string;
    chapterNumber: string;
  }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { addToast } = useToast();
  const { theme: appTheme } = useTheme();
  const compact = useMediaQuery("(max-width: 767px)", false);

  const chapter_number = Number(chapterNumber);
  const library_id = Number(libraryId);
  const novel_id = Number(novelId);
  const requestedChapterKey = searchParams.get("chapter_key") || undefined;
  const citationOffsetValue = searchParams.get("offset");
  const citationOffset = citationOffsetValue === null ? NaN : Number(citationOffsetValue);

  const [chapter, setChapter] = useState<ChapterContent | null>(null);
  const loadedChapterIdentity=useMemo(()=>chapterIdentity(chapter) ?? undefined,[chapter]);
  const [novel, setNovel] = useState<Novel | null>(null);
  usePageTitle(chapter && novel ? `${chapter.title} · ${displayTitle(novel)}` : null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [progressConflict, setProgressConflict] = useState(false);
  const [progressConflictCode, setProgressConflictCode] = useState<string>();
  const chapterIdentityConflict=["chapter_identity_required","chapter_manifest_changed"].includes(progressConflictCode || "");
  useEffect(() => {
    const pending = getQueuedProgress().find((item) => item.novelId === novel_id && item.blocked);
    setProgressConflict(!!pending);
    setProgressConflictCode(pending?.conflictCode);
    const conflict = (event: Event) => {
      if ((event as CustomEvent).detail?.novelId === novel_id) {
        setProgressConflict(true);
        setProgressConflictCode((event as CustomEvent).detail?.code);
      }
    };
    window.addEventListener("nexus-progress-conflict", conflict);
    return () => window.removeEventListener("nexus-progress-conflict", conflict);
  }, [novel_id]);
  const reconcileProgress = async (choice: "server" | "device") => {
    try {
      const saved = await chapterService.resolveProgressConflict(novel_id, choice);
      if (saved) {
        const savedKey=chapterIdentity(saved)?.chapter_key;
        setProgress(saved);
        setRestoredPosition(false);
        setProgressConflict(false);
        if (choice === "server" && saved.chapter_number != null && saved.chapter_number !== chapter_number) navigate(`/library/${library_id}/novels/${novel_id}/${saved.chapter_number}${savedKey ? `?chapter_key=${encodeURIComponent(savedKey)}` : ""}`);
      }
    } catch { addToast("Couldn’t synchronize the position. Your local save is still kept.", "error"); }
  };
  useEffect(() => {
    const changed = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.novelId !== novel_id || !chapter) return;
      const identity = chapterIdentity(chapter);
      if (identity && (identity.manifest_epoch !== detail.manifest_epoch || identity.manifest_revision !== detail.manifest_revision)) {
        setProgressConflict(true); setProgressConflictCode("chapter_manifest_changed");
      }
    };
    window.addEventListener(CHAPTER_MANIFEST_CHANGED, changed);
    return () => window.removeEventListener(CHAPTER_MANIFEST_CHANGED, changed);
  }, [novel_id, chapter]);
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  const chapterScope = `${generation}:${library_id}:${novel_id}`;
  const [indexState, setIndexState] = useState<{ scope: string; kind: "loading" | "live" | "cached" | "partial" | "none"; entries: ChapterSummary[]; error: string | null }>({ scope: "", kind: "loading", entries: [], error: null });
  const [navigationState, setNavigationState] = useState<{ scope: string; kind: "loading" | "live" | "cached" | "none"; data: ChapterNavigationResponse | null }>({ scope: "", kind: "loading", data: null });
  const chapters = useMemo(() => indexState.scope === chapterScope ? indexState.entries : [], [indexState, chapterScope]);
  const chaptersLoading = indexState.scope !== chapterScope || indexState.kind === "loading";
  const chaptersError = indexState.scope === chapterScope ? indexState.error : null;
  const typo = useReaderTypography(novel_id);
  const t = typo.typography;
  const readerTheme = resolveReaderTheme(t.theme, appTheme);
  const [authorNotes, setAuthorNotes] = useState<AuthorNotesMode>(readAuthorNotesMode);
  const [layout, setLayout] = useState<ReaderLayout>(readLayout);
  const [shortcutsEnabled, setShortcutsEnabled] = useState(readShortcutsEnabled);
  useEffect(() => {
    const reload = () => {
      setLayout(readLayout()); setAuthorNotes(readAuthorNotesMode()); setShortcutsEnabled(readShortcutsEnabled());
    };
    window.addEventListener("nexus-reader-preferences-loaded", reload);
    return () => window.removeEventListener("nexus-reader-preferences-loaded", reload);
  }, []);
  const [progress, setProgress] = useState<ReadingProgress | null>(null);
  const [percent, setPercent] = useState(0);
  const [annotations, setAnnotations] = useState<ReadingAnnotation[]>([]);
  const [restoredPosition, setRestoredPosition] = useState(false);
  const [locatorReview, setLocatorReview] = useState(false);
  const [readingHistory, setReadingHistory] = useState<{ chapters_touched: number; active_days: number; current_streak_days: number } | null>(null);
  const [recap, setRecap] = useState<RecapData | null>(null);
  const [recapLoading, setRecapLoading] = useState(false);
  const [hiatus, setHiatus] = useState<{ state: string; confidence: number; reason: string } | null>(null);
  // Overlays
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [listenOpen, setListenOpen] = useState(false);
  const [audioPlaying,setAudioPlaying] = useState(false);
  const [noteQuote, setNoteQuote] = useState<string | null>(null);
  const [annotationsOpen, setAnnotationsOpen] = useState(false);
  const [recapOpen, setRecapOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [toolsPassage, setToolsPassage] = useState<PassageAnchor | null>(null);
  const passageAnchor = useRef<PassageAnchor | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchBlocks, setSearchBlocks] = useState<SearchBlock[]>([]);
  const [versionAnchor, setVersionAnchor] = useState<{ version: string; locator: TextLocator } | null>(null);
  const [versionChapter, setVersionChapter] = useState(chapter_number);
  const [versionChapterKey, setVersionChapterKey] = useState<string | undefined>();
  const [translation, setTranslation] = useState<TranslationVariant | null>(null);
  const [parallelText, setParallelText] = useState(false);
  const pairedDocument = useMemo(() => chapter?.document && translation && parallelText
    ? parallelDocument(chapter.document, translation.document, translation.language) : undefined,
    [chapter?.document, translation, parallelText]);
  useEffect(() => { setTranslation(null); setParallelText(false); }, [novel_id, chapter_number]);
  useEffect(() => {
    if (translation && chapter?.document?.content_version && translation.source_version !== chapter.document.content_version) {
      setTranslation(null);
      addToast("The source text changed. Showing the current original chapter.", "info");
    }
  }, [translation, chapter?.document?.content_version, addToast]);
  const [barsFocused, setBarsFocused] = useState(false);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const location = useLocation();
  const variant = translation ? `${parallelText ? "parallel" : "translation"}:${translation.id}` : "original";
  const readerAssetsReady = useReaderAssetsReady(contentRef, chapter
    ? `${chapter.id}:${chapter.document?.content_version || "legacy"}:${variant}:${authorNotes}:${t.font}` : null);
  const pendingReflow = useRef<{ chapterId: number; locator?: TextLocator; start: boolean; variant: string } | null>(null);
  const lastVisible = useRef<TextLocator | undefined>(undefined);
  const noteLocator = useRef<{ locator?: TextLocator; version?: string; variant: string } | null>(null);
  const selectedPassage = useRef<{ chapterId: number; locator: TextLocator; quote: string; version?: string; variant: string } | null>(null);
  useEffect(() => {
    selectedPassage.current = null;
    passageAnchor.current = null;
    setToolsPassage(null);
    const remember = () => {
      if (!chapter || !contentRef.current) return;
      if (window.getSelection()?.toString()) passageAnchor.current = variant === "original" && chapter.document
        ? capturePassage(contentRef.current, chapter.document) : null;
      if(passageAnchor.current && chapterIdentity(chapter)) Object.assign(passageAnchor.current,expectedChapterIdentity(chapterIdentity(chapter)!,chapterSourceVersion(chapter,true)));
      const locator = selectedTextLocator(contentRef.current);
      if (locator) selectedPassage.current = { chapterId: chapter.id, locator, quote: window.getSelection()?.toString().trim() || "",
        version: chapter.document?.content_version, variant };
    };
    document.addEventListener("selectionchange", remember);
    return () => document.removeEventListener("selectionchange", remember);
  }, [chapter, variant]);
  const restoredKey = useRef("");
  const navigationEpoch = useRef(0);
  const openChapterSearch = useCallback(() => {
    const content = contentRef.current;
    if (!content) return;
    setSearchBlocks(Array.from(content.querySelectorAll<HTMLElement>("[data-block-id]")).map(block => ({ id: block.dataset.blockId!, text: block.textContent || "" })));
    setSearchOpen(true);
  }, []);
  useEffect(() => {
    const find = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "f") return;
      if ((event.target as HTMLElement | null)?.closest("input, textarea, [contenteditable='true'], [role='dialog']")) return;
      event.preventDefault(); openChapterSearch();
    };
    window.addEventListener("keydown", find);
    return () => window.removeEventListener("keydown", find);
  }, [openChapterSearch]);
  const jumpSearchMatch = (match: ChapterMatch) => {
    navigationEpoch.current++;
    setSearchOpen(false);
    const content = contentRef.current;
    if (!content) return;
    const block = Array.from(content.querySelectorAll<HTMLElement>("[data-block-id]")).find(element => element.dataset.blockId === match.locator.blockId);
    const toggle = block?.closest(".reader-author-note")?.querySelector<HTMLButtonElement>('button[aria-expanded="false"]');
    toggle?.click();
    const jump = () => {
      if (!restoreTextLocator(content, match.locator, { paged: layout === "paged" }).matched) {
        addToast("This match is hidden in the current view. Show author notes or switch to the original text, then search again.", "info");
      } else selectChapterMatch(content, match);
    };
    if (!toggle) jump(); window.requestAnimationFrame(jump);
  };
  const capturePlace = useCallback(() => {
    if (!contentRef.current || !chapter || !restoredPosition || locatorReview) return;
    pendingReflow.current = { chapterId: chapter.id, variant, start: contentRef.current.scrollTop < 2 && contentRef.current.scrollLeft < 2,
      locator: visibleBlockLocator(contentRef.current, layout === "paged") };
  }, [chapter, restoredPosition, locatorReview, layout, variant]);
  useEffect(() => {
    window.addEventListener("nexus-reader-before-style-change", capturePlace);
    return () => window.removeEventListener("nexus-reader-before-style-change", capturePlace);
  }, [capturePlace]);
  useLayoutEffect(() => {
    const saved = pendingReflow.current, content = contentRef.current;
    if (!saved || !content || saved.chapterId !== chapter?.id) return;
    pendingReflow.current = null;
    const epoch = navigationEpoch.current;
    const restore = () => {
      if (epoch !== navigationEpoch.current) return;
      if (saved.start) { content.scrollTop = 0; content.scrollLeft = 0; }
      else if (saved.locator && !restoreTextLocator(content, saved.locator, { paged: layout === "paged", blockOnly: saved.variant !== variant }).matched) setLocatorReview(true);
    };
    restore();
    let cancelled = false;
    void document.fonts?.ready.then(() => { if (!cancelled) restore(); });
    const frame = window.requestAnimationFrame(restore);
    const timer = window.setTimeout(restore, 250);
    return () => { cancelled = true; window.cancelAnimationFrame(frame); window.clearTimeout(timer); };
  }, [chapter?.id, t.fontSize, t.lineHeight, t.width, t.font, t.letterSpacing, t.wordSpacing, t.paragraphStyle, t.justify, t.hyphenate, layout, authorNotes, compact, variant, listenOpen, settingsOpen, locatorReview, progressConflict]);
  const chaptersButtonRef = useRef<HTMLButtonElement | null>(null);

  // The shortcuts switch can also change in Settings › Reading (another tab or page).
  useEffect(() => {
    const sync = () => setShortcutsEnabled(readShortcutsEnabled());
    window.addEventListener("nexus-reader-shortcuts", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("nexus-reader-shortcuts", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => {
    const generation = storageGeneration();
    let cancelled = false;
    // Bind both requests to the session in which this navigation began. A
    // restart in another tab must not lend its new key to an older chapter load.
    const beforeLoad = chapterService.getCachedReadingProgress(novel_id);
    const fetchData = async () => {
      const progressRequest = chapterService.getReadingProgress(novel_id)
        .then(value => ({ value, error: null as unknown }))
        .catch(error => ({ value: beforeLoad, error }));
      try {
        setLoading(true);
        const chapterData = await chapterService.getChapterContentByNumber(chapter_number, library_id, novel_id, requestedChapterKey);
        const reading = await progressRequest;
        if (cancelled || generation !== storageGeneration()) return;
        const latest = chapterService.getCachedReadingProgress(novel_id);
        const changed = (axios.isAxiosError(reading.error) && reading.error.response?.data?.detail?.code === "reading_run_changed")
          || (beforeLoad?.reading_run_key && reading.value?.reading_run_key && beforeLoad.reading_run_key !== reading.value.reading_run_key)
          || (reading.value?.reading_run_key && latest?.reading_run_key && reading.value.reading_run_key !== latest.reading_run_key);
        const savedProgress = changed ? beforeLoad || reading.value : reading.value;
        if (changed) { setProgressConflict(true); setProgressConflictCode("reading_run_changed"); }
        void novelService.getHiatusStatus(library_id, novel_id).then(value=>{if(!cancelled&&generation===storageGeneration())setHiatus(value);}).catch(() => {if(!cancelled&&generation===storageGeneration())setHiatus(null);});
        setChapter(chapterData);
        setProgress(savedProgress);
        setRestoredPosition(false);
        void offlineReaderStore.save({ ...chapterData, library_id }).catch(() => undefined);

        if (chapterData && chapterData.novel_id) {
          const novelData = await novelService.getNovelById(library_id, chapterData.novel_id);
          if (cancelled || generation !== storageGeneration()) return;
          setNovel(novelData);
          void offlineReaderStore.save({ ...chapterData, library_id, novel_title: novelData.title }).catch(() => undefined);
        }
        setError(null);
      } catch (err) {
        if (cancelled || generation !== storageGeneration()) return;
        const offlineChapter = isNetworkError(err) ? await offlineReaderStore.get(novel_id, chapter_number).catch(() => null) : null;
        if (cancelled || generation !== storageGeneration()) return;
        if (offlineChapter && (!requestedChapterKey || offlineChapter.chapter_key === requestedChapterKey)) {
          setChapter(offlineChapter);
          setProgress(beforeLoad);
          const latest = chapterService.getCachedReadingProgress(novel_id);
          if (beforeLoad?.reading_run_key && latest?.reading_run_key && beforeLoad.reading_run_key !== latest.reading_run_key) {
            setProgressConflict(true); setProgressConflictCode("reading_run_changed");
          }
          setError("Offline mode: showing the last cached copy.");
        } else {
          const detail = axios.isAxiosError(err) ? String(err.response?.data?.detail || "") : "";
          setChapter(null);
          setError(detail === "Chapter content is not downloaded"
            ? "This chapter has not been downloaded yet. Queue it from the story page, then come back to read or listen."
            : "Couldn’t load this chapter. Check your connection and try again.");
        }
        logRequestFailure(err,"Could not load reader content");
      } finally {
        if (!cancelled && generation === storageGeneration()) setLoading(false);
      }
    };

    fetchData();
    return () => { cancelled = true; };
  }, [chapter_number, library_id, novel_id, requestedChapterKey]);

  useEffect(() => {
    let active=true;const generation=storageGeneration();setAnnotations([]);
    void chapterService.getReadingAnnotations(novel_id).then(value=>{if(active&&generation===storageGeneration())setAnnotations(value);}).catch(()=>undefined);
    return()=>{active=false;};
  }, [novel_id]);

  useEffect(() => {
    let active=true;const generation=storageGeneration();setReadingHistory(null);
    void chapterService.getReadingHistory(novel_id).then(value=>{if(active&&generation===storageGeneration())setReadingHistory(value);}).catch(()=>{if(active&&generation===storageGeneration())setReadingHistory(null);});
    return()=>{active=false;};
  }, [novel_id, chapter_number]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter || !readerAssetsReady) return;
    const key = `${chapter.id}:${chapter.document?.content_version || ""}:${progress?.revision || 0}:${location.key}`;
    if (restoredKey.current === key) return;
    const frame = window.requestAnimationFrame(() => {
      const routed = (location.state as { readerAnchor?: ReadingAnnotation } | null)?.readerAnchor;
      const pending = getQueuedProgress().find(item => item.novelId === novel_id && item.chapter === chapter.chapter_number && !!item.chapterIdentity && item.chapterIdentity.chapter_key === chapterIdentity(chapter)?.chapter_key
        && (item.readingRunKey ?? null) === (progress?.reading_run_key ?? null));
      const local: ReadingProgress | undefined = pending ? { chapter_key:pending.chapterIdentity?.chapter_key, chapter_number: pending.chapter, percent: pending.percent, position: pending.position,
        block_id: pending.blockId, text_offset: pending.textOffset, text_quote: pending.textQuote, quote_prefix: pending.quotePrefix,
        quote_suffix: pending.quoteSuffix, locator_content_version: pending.contentVersion, locator_variant: pending.locatorVariant } : undefined;
      const identity = chapterIdentity(chapter);
      const routedKey = routed && (routed as ReadingAnnotation & { chapter_key?: string }).chapter_key;
      const target = routed?.chapter_number === chapter.chapter_number && (!identity || routedKey === identity.chapter_key) ? routed
        : local || (progress?.chapter_number === chapter.chapter_number && (!identity || progress.chapter_key === identity.chapter_key) ? progress : undefined);
      const citation = searchParams.get("block");
      let review = savedChapterPlaceNeedsReview(progress,chapter);
      if (citation) restoreTextLocator(content, { blockId: citation }, { paged: layout === "paged", blockOnly: true });
      else if (target) {
        const renditionChanged = Boolean(target.locator_variant && target.locator_variant !== variant);
        const resolved = !target.position && !target.percent && !routed
          ? { matched: true } : restoreTextLocator(content, savedLocator(target), {
            paged: layout === "paged", blockOnly: renditionChanged,
            trustBlock: !target.locator_content_version || target.locator_content_version === chapter.document?.content_version,
          });
        if (!resolved.matched) {
          const ratio = Math.min(100, Math.max(0, target.percent || 0)) / 100;
          if (layout === "paged") {
            const width = content.clientWidth || 1;
            content.scrollLeft = Math.round(ratio * Math.max(content.scrollWidth - width, 0) / width) * width;
          } else content.scrollTop = ratio * Math.max(content.scrollHeight - content.clientHeight, 0);
          review = Boolean(target.text_quote || target.locator_content_version);
        } else if (!target.position && !target.percent && !routed) { content.scrollTop = 0; content.scrollLeft = 0; }
      } else { content.scrollTop = 0; content.scrollLeft = 0; }
      restoredKey.current = key;
      setLocatorReview(review);
      lastVisible.current = visibleBlockLocator(content, layout === "paged");
      setRestoredPosition(true);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [chapter, progress, layout, variant, location.key, location.state, novel_id, searchParams, readerAssetsReady]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter || !restoredPosition) return;
    const relocate = () => {
      if (!lastVisible.current || locatorReview) return;
      restoreTextLocator(content, lastVisible.current, { paged: layout === "paged" });
    };
    window.addEventListener("resize", relocate);
    document.fonts?.addEventListener("loadingdone", relocate);
    // load/error do not bubble. Capture them on the reading container only;
    // illustrations in a separate viewer must not relocate the story.
    const imageSettled = (event: Event) => {
      if (event.target instanceof HTMLImageElement) relocate();
    };
    content.addEventListener("load", imageSettled, true);
    content.addEventListener("error", imageSettled, true);
    return () => {
      window.removeEventListener("resize", relocate); document.fonts?.removeEventListener("loadingdone", relocate);
      content.removeEventListener("load", imageSettled, true); content.removeEventListener("error", imageSettled, true);
    };
  }, [chapter, restoredPosition, locatorReview, layout]);

  const acceptLocatedPosition = async () => {
    const content = contentRef.current;
    if (!content || !chapter) return;
    const percent = scrollPercent(layout === "paged" ? content.scrollLeft : content.scrollTop,
      layout === "paged" ? content.scrollWidth - content.clientWidth : content.scrollHeight - content.clientHeight);
    try {
      const locator = visibleBlockLocator(content, layout === "paged");
      const saved = await chapterService.updateReadingProgress(novel_id, chapter.chapter_number, Math.round(layout === "paged" ? content.scrollLeft : content.scrollTop), percent,
        { ...locator, chapterIdentity: chapterIdentity(chapter) ?? undefined, expectedContentVersion: chapterSourceVersion(chapter,true), readingRunKey: progress?.reading_run_key ?? null, contentVersion: chapter.document?.content_version, locatorVariant: variant, intent: "reconcile" });
      const pending = getQueuedProgress().find(item => item.novelId === novel_id);
      if (saved || (pending?.intent === "reconcile" && !pending.blocked)) {
        pendingReflow.current = { chapterId: chapter.id, locator, variant, start: content.scrollTop < 2 && content.scrollLeft < 2 };
        setLocatorReview(false);
        setProgressConflict(false);
      }
    } catch { addToast("Couldn’t save this location. Your earlier anchor is still kept.", "error"); }
  };

  const chapterContent = chapter?.content;
  useEffect(() => {
    const content = contentRef.current;
    if (!content || chapterContent === undefined || !Number.isFinite(citationOffset) || citationOffset < 0) return;
    // Evidence stores source-character offsets. The reader renders normalized
    // paragraphs, so navigate proportionally rather than claiming a brittle,
    // exact DOM range after source formatting changes.
    const ratio = Math.min(1, citationOffset / Math.max(chapterContent.length, 1));
    const frame = window.requestAnimationFrame(() => {
      content.scrollTop = ratio * Math.max(content.scrollHeight - content.clientHeight, 0);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [chapter?.id, chapterContent, citationOffset]);

  useEffect(() => {
    let live = true;
    const current = () => live && generation === storageGeneration();
    setIndexState({ scope: chapterScope, kind: "loading", entries: [], error: null });
    void loadChapterIndex((skip, limit) => chapterService.getChapters(novel_id, { skip, limit }), current).then(entries => {
      if (!current()) return;
      cacheChapterIndex(novel_id, entries, generation);
      setIndexState({ scope: chapterScope, kind: "live", entries, error: null });
    }).catch(error => {
      if (!current()) return;
      if (error instanceof ChapterIndexLimitError) setIndexState({ scope: chapterScope, kind: "partial", entries: error.entries, error: error.message });
      else {
        const entries = isNetworkError(error) ? cachedChapterIndex(novel_id) : null;
        setIndexState({ scope: chapterScope, kind: entries ? "cached" : "none", entries: entries ?? [], error: entries ? "Showing the last saved chapter index. Connect to check for changes." : "Couldn’t load the chapter list. Previous and next use verified neighbors when available." });
      }
    });
    return () => { live = false; };
  }, [novel_id, generation, chapterScope]);
  useEffect(() => {
    let live = true;
    const scope = `${chapterScope}:${chapter_number}`;
    const current = () => live && generation === storageGeneration();
    setNavigationState({ scope, kind: "loading", data: null });
    void chapterService.getNavigation(novel_id, chapter_number,requestedChapterKey ?? (chapter?.chapter_number === chapter_number ? loadedChapterIdentity : undefined)).then(data => {
      if (!validNavigation(data, novel_id, chapter_number)) throw new Error("Invalid adjacent chapters");
      if (!current()) return;
      cacheChapterNavigation(data, generation);
      setNavigationState({ scope, kind: "live", data });
    }).catch(error => {
      if (!current()) return;
      const data = isNetworkError(error) ? cachedChapterNavigation(novel_id, chapter_number) : null;
      setNavigationState({ scope, kind: data ? "cached" : "none", data });
    });
    return () => { live = false; };
  }, [novel_id, chapter_number, generation, chapterScope,loadedChapterIdentity,requestedChapterKey,chapter?.chapter_number]);

  const goToChapter = useCallback((target: number) => {
    const candidate=chapters.find(row=>row.chapter_number===target)
      || [navigationState.data?.previous,navigationState.data?.next].find(row=>row?.chapter_number===target);
    const key=chapterIdentity(candidate)?.chapter_key;
    navigate(`/library/${library_id}/novels/${novel_id}/${target}${key?`?chapter_key=${encodeURIComponent(key)}`:""}`);
  }, [library_id, novel_id, navigate,chapters,navigationState]);

  const indexedNeighbors = useMemo(() => chapterNeighbors(chapters, chapter_number), [chapters, chapter_number]);
  const scopedNavigation = navigationState.scope === `${chapterScope}:${chapter_number}` ? navigationState : null;
  const navigationData = scopedNavigation?.data && (!chapter || chapter.chapter_number !== chapter_number || scopedNavigation.data.chapter_id === chapter.id) ? scopedNavigation.data : null;
  const indexKind = indexState.scope === chapterScope ? indexState.kind : "loading";
  const indexComplete = indexKind === "live" || indexKind === "cached";
  const resolvedNavigation = chooseChapterNavigation(indexedNeighbors, indexKind, navigationData, scopedNavigation?.kind);
  const previousEntry = resolvedNavigation.previous, nextEntry = resolvedNavigation.next;
  const navigationKnown = resolvedNavigation.source !== "none";
  const navigationLive = resolvedNavigation.source === "live";
  const previousChapter = () => { if (previousEntry) goToChapter(previousEntry.chapter_number); };
  const nextChapter = () => { if (nextEntry) goToChapter(nextEntry.chapter_number); };

  const paging = useReaderPaging({
    contentRef,
    paged: layout === "paged",
    layoutKey: `${chapter?.id ?? 0}-${t.width}-${t.fontSize}-${t.lineHeight}-${t.font}-${t.letterSpacing}-${t.wordSpacing}-${t.paragraphStyle}-${compact}-${listenOpen}`,
    onPreviousChapter: previousChapter,
    onNextChapter: nextChapter,
  });
  const { setChromeHidden } = paging;

  // Progress saving (debounced, queued offline by the service), live percent and
  // immersive bars: scrolling down hides them, scrolling up shows them again.
  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter) return;
    let timeout: number | undefined;
    let frame = 0;
    let lastTop = content.scrollTop;
    const onScroll = () => {
      const paged = layout === "paged";
      const offset = paged ? content.scrollLeft : content.scrollTop;
      const maxOffset = paged ? content.scrollWidth - content.clientWidth : content.scrollHeight - content.clientHeight;
      const value = scrollPercent(offset, maxOffset);
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        setPercent(value);
        if (!locatorReview) lastVisible.current = visibleBlockLocator(content, paged);
      });
      if (!paged) {
        const delta = content.scrollTop - lastTop;
        if (delta > 12 && content.scrollTop > 120 && value < 98) setChromeHidden(true);
        else if (delta < -12 || value >= 98) setChromeHidden(false);
        lastTop = content.scrollTop;
      }
      window.clearTimeout(timeout);
      if (!restoredPosition || !readerAssetsReady || locatorReview || audioPlaying) return;
      timeout = window.setTimeout(() => {
        chapterService.updateReadingProgress(novel_id, chapter.chapter_number, Math.round(offset), value, { ...visibleBlockLocator(content, paged), chapterIdentity: chapterIdentity(chapter) ?? undefined, expectedContentVersion: chapterSourceVersion(chapter,true), readingRunKey: progress?.reading_run_key ?? null, locatorVariant: variant, contentVersion: translation ? translation.source_version : chapter.document?.content_version })
          .catch((err) => logRequestFailure(err,"Failed to save reading progress"));
      }, 500);
    };
    content.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      content.removeEventListener("scroll", onScroll);
      window.clearTimeout(timeout);
      window.cancelAnimationFrame(frame);
    };
  }, [chapter, novel_id, restoredPosition, readerAssetsReady, locatorReview, layout, setChromeHidden, translation, variant, audioPlaying, progress?.reading_run_key]);

  useEffect(() => { setChromeHidden(false); setPercent(0); }, [chapter?.id, layout, setChromeHidden]);
  useReadingHeartbeat(novel_id, chapter?.id);

  const saveAudioPassage = useCallback((locator:TextLocator,completed:boolean) => {
    if(!chapter?.document || loading || chapter.chapter_number!==chapter_number || variant!=="original" || progressConflict || locatorReview)return;
    const blocks=chapter.document.blocks;
    const index=blocks.findIndex(block=>block.id===locator.blockId);
    if(index<0)return;
    const target=completed ? quoteLocator(blocks,index,blocks[index].text.length) : locator;
    const total=blocks.reduce((sum,block)=>sum+block.text.length,0);
    const before=blocks.slice(0,index).reduce((sum,block)=>sum+block.text.length,0);
    const value=completed ? 100 : Math.min(99.9,100*(before+(target.textOffset || 0))/Math.max(1,total));
    setPercent(value);
    void chapterService.updateReadingProgress(novel_id,chapter.chapter_number,0,value,{...target,chapterIdentity:chapterIdentity(chapter) ?? undefined,expectedContentVersion:chapterSourceVersion(chapter,true),readingRunKey:progress?.reading_run_key ?? null,contentVersion:chapter.document.content_version,locatorVariant:"original"}).catch(()=>addToast("Your audio position could not be synchronized. It remains saved on this device.","error"));
  },[chapter,loading,chapter_number,variant,progressConflict,locatorReview,novel_id,addToast,progress?.reading_run_key]);
  const readAudioPassage = (locator:TextLocator) => {
    if(!contentRef.current || variant!=="original")return;
    navigationEpoch.current++;
    pendingReflow.current=null;
    const result=restoreTextLocator(contentRef.current,locator,{paged:layout==="paged"});
    if(!result.matched){addToast("This passage is hidden in the current view. Check author-note visibility in Text settings.","info");return;}
    lastVisible.current=locator;saveAudioPassage(locator,false);
  };

  const changeAuthorNotes = (mode: AuthorNotesMode) => { capturePlace(); setAuthorNotes(mode); writeAuthorNotesMode(mode); };
  const changeLayout = (next: ReaderLayout) => { capturePlace(); setLayout(next); writeLayout(next); };
  const changeShortcuts = (enabled: boolean) => { setShortcutsEnabled(enabled); writeShortcutsEnabled(enabled); };

  const addAnnotation = useCallback(async (annotationType: "bookmark" | "note", note?: string, quote?: string, anchor?: { locator?: TextLocator; version?: string; variant: string }) => {
    if (!chapter || !contentRef.current) return;
    const content = contentRef.current;
    const value = layout === "paged"
      ? scrollPercent(content.scrollLeft, content.scrollWidth - content.clientWidth)
      : scrollPercent(content.scrollTop, content.scrollHeight - content.clientHeight);
    const selection = quote ?? (window.getSelection()?.toString().trim() || "");
    const locator = anchor?.locator || (annotationType === "note" ? selectedTextLocator(content) : undefined) || visibleBlockLocator(content, layout === "paged");
    try {
      const created = await chapterService.createReadingAnnotation(novel_id, {
        ...(chapterIdentity(chapter) ? expectedChapterIdentity(chapterIdentity(chapter)!,chapterSourceVersion(chapter,true)) : {}),
        chapter_number: chapter.chapter_number,
        annotation_type: annotationType,
        position: Math.round(layout === "paged" ? content.scrollLeft : content.scrollTop),
        percent: value,
        quote: selection || undefined,
        note: note || undefined,
        block_id: locator?.blockId, text_offset: locator?.textOffset, text_quote: locator?.textQuote,
        quote_prefix: locator?.quotePrefix, quote_suffix: locator?.quoteSuffix,
        locator_content_version: anchor?.version || chapter.document?.content_version,
        locator_variant: anchor?.variant || variant,
      });
      setAnnotations((current) => [created, ...current]);
      addToast(annotationType === "bookmark" ? "Bookmarked." : "Note saved.", "success");
    } catch (err) {
      logRequestFailure(err,"Failed to save reader annotation");
      addToast(annotationType === "bookmark" ? "Couldn’t save the bookmark." : "Couldn’t save the note.", "error");
    }
  }, [chapter, novel_id, layout, addToast, variant]);

  const removeAnnotation = useCallback(async (id: number) => {
    try {
      await chapterService.deleteReadingAnnotation(id);
      setAnnotations((current) => current.filter((annotation) => annotation.id !== id));
    } catch {
      addToast("Couldn’t delete it. Try again.", "error");
    }
  }, [addToast]);

  const chapterBookmark = annotations.find((a) => a.chapter_number === chapter_number
    && (!loadedChapterIdentity || (a as ReadingAnnotation & {chapter_key?:string}).chapter_key === loadedChapterIdentity.chapter_key)
    && a.annotation_type === "bookmark");
  const toggleBookmark = useCallback(() => {
    if (chapterBookmark) {
      void removeAnnotation(chapterBookmark.id).then(() => addToast("Bookmark removed."));
    } else {
      void addAnnotation("bookmark");
    }
  }, [chapterBookmark, removeAnnotation, addAnnotation, addToast]);

  const jumpToAnnotation = (annotation: ReadingAnnotation) => {
    navigationEpoch.current++;
    setAnnotationsOpen(false);
    if(annotation.chapter_number == null) { addToast("This note’s original chapter needs identity review. Its saved text is preserved.","info"); return; }
    const annotationKey=(annotation as ReadingAnnotation & {chapter_key?:string}).chapter_key;
    if (loadedChapterIdentity && !annotationKey) { addToast("This older note has no verified chapter identity. Review it from your chapter history.", "info"); return; }
    if (annotation.chapter_number !== chapter_number || (annotationKey && annotationKey !== loadedChapterIdentity?.chapter_key)) { navigate(`/library/${library_id}/novels/${novel_id}/${annotation.chapter_number}${annotationKey ? `?chapter_key=${encodeURIComponent(annotationKey)}` : ""}`, { state: { readerAnchor: annotation } }); return; }
    const content = contentRef.current;
    if (!content || !chapter) return;
    const locator = savedLocator(annotation);
    if (!locator.textQuote && annotation.quote) locator.textQuote = annotation.quote.slice(0, 160);
    const resolved = restoreTextLocator(content, locator, { paged: layout === "paged",
      blockOnly: Boolean(annotation.locator_variant && annotation.locator_variant !== variant),
      trustBlock: !annotation.locator_content_version || annotation.locator_content_version === chapter.document?.content_version });
    if (!resolved.matched) {
      if (layout === "paged") paging.goToPage(Math.round((annotation.percent / 100) * (paging.pageCount - 1)));
      else content.scrollTop = (annotation.percent / 100) * Math.max(content.scrollHeight - content.clientHeight, 0);
      addToast("The exact passage is unavailable in this text or view. Showing its approximate location; the annotation is preserved.", "info");
    }
  };

  const keepChapterOffline = async () => {
    if (!chapter) return;
    try {
      await offlineReaderStore.save(chapter, { pinned: true });
      const count = await offlineReaderStore.countForNovel(novel_id);
      addToast(`Saved offline. ${count} chapter${count === 1 ? "" : "s"} of this story are on this device.`, "success");
    } catch {
      addToast("Couldn’t save this chapter on this device.", "error");
    }
  };

  const downloadEpub = async () => {
    try {
      download(await chapterService.exportNovelEpub(novel_id), `${novel ? displayTitle(novel) : "story"}.epub`);
    } catch {
      addToast("Couldn’t create the EPUB. Try again later.", "error");
    }
  };

  const exportReadingState = () => {
    const payload = { exported_at: new Date().toISOString(), novel_id, novel_title: novel?.title, progress, annotations,
      unsynchronized_positions: getQueuedProgress().filter(item => item.novelId === novel_id) };
    download(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }), `nexus-reading-state-${novel_id}.json`);
  };

  const copyQuote = async () => {
    const quote = window.getSelection()?.toString().trim();
    if (!quote) { addToast("Select some text in the chapter first, then choose Copy quote."); return; }
    const payload = `“${quote}”\n— ${novel?.title || "Nexus"}, chapter ${chapter?.chapter_number ?? ""}`;
    try { await navigator.clipboard.writeText(payload); addToast("Quote copied.", "success"); }
    catch { download(new Blob([payload], { type: "text/plain" }), "nexus-quote.txt"); }
  };

  const openRecap = async () => {
    setRecapOpen(true);
    setRecapLoading(true);
    try { setRecap(await chapterService.getSpoilerSafeRecap(novel_id)); }
    catch { setRecap(null); }
    finally { setRecapLoading(false); }
  };

  const openNote = () => {
    const live = contentRef.current ? selectedTextLocator(contentRef.current) : undefined;
    const remembered = selectedPassage.current?.chapterId === chapter?.id ? selectedPassage.current : null;
    noteLocator.current = { locator: live || remembered?.locator || (contentRef.current ? visibleBlockLocator(contentRef.current, layout === "paged") : undefined),
      version: remembered?.version || chapter?.document?.content_version, variant: remembered?.variant || variant };
    setNoteQuote(live ? window.getSelection()?.toString().trim() || "" : remembered?.quote || "");
    selectedPassage.current = null;
  };

  const next = () => (layout === "paged" ? paging.advance(1) : nextChapter());
  const previous = () => (layout === "paged" ? paging.advance(-1) : previousChapter());
  const anyOverlay = drawerOpen || settingsOpen || noteQuote !== null || annotationsOpen || recapOpen || shortcutsOpen || versionsOpen || searchOpen || toolsOpen;
  const barsHidden = paging.chromeHidden && !barsFocused && !anyOverlay && !listenOpen;
  useEffect(() => {
    const content = contentRef.current;
    if (!content || !restoredPosition || !readerAssetsReady || locatorReview) return;
    let frame = 0;
    const until = performance.now() + 300;
    const refresh = () => {
      // The bars animate over the prose without scrolling it. Keep the visible
      // anchor current as their clipping edge moves, including reduced motion.
      lastVisible.current = visibleBlockLocator(content, layout === "paged");
      if (performance.now() < until) frame = window.requestAnimationFrame(refresh);
    };
    frame = window.requestAnimationFrame(refresh);
    return () => window.cancelAnimationFrame(frame);
  }, [barsHidden, restoredPosition, readerAssetsReady, locatorReview, layout]);
  useReaderShortcuts({
    next: () => { if (!anyOverlay && chapter && (layout === "paged" || !!nextEntry)) next(); },
    previous: () => { if (!anyOverlay && chapter && (layout === "paged" || !!previousEntry)) previous(); },
    bookmark: () => { if (!anyOverlay) toggleBookmark(); },
    chapters: () => setDrawerOpen(true),
    textSettings: () => { capturePlace(); setSettingsOpen(true); },
    smaller: () => typo.set("fontSize", (v) => Math.max(FONT_SIZE_MIN, v - 1)),
    larger: () => typo.set("fontSize", (v) => Math.min(FONT_SIZE_MAX, v + 1)),
    help: () => setShortcutsOpen(true),
  }, shortcutsEnabled);

  const words = useMemo(() => (chapterContent ? chapterContent.split(/\s+/).filter(Boolean).length : 0), [chapterContent]);

  if (loading && !chapter) return <div className="reader-state" role="status" data-reader-theme={readerTheme}>Loading chapter…</div>;
  if (error && !chapter) {
    return (
      <div className="reader-state" data-reader-theme={readerTheme}>
        <h1>Chapter unavailable</h1>
        <p>{error}</p>
        <Link className="ui-button ui-button--secondary" to={`/library/${library_id}/novels/${novel_id}`}><span className="ui-button__label">Back to story</span></Link>
      </div>
    );
  }
  if (!chapter) return <div className="reader-state" data-reader-theme={readerTheme}><h1>Chapter not found</h1></div>;

  const storyTitle = novel ? displayTitle(novel) : "Story";
  const totalChapters = indexComplete ? chapters.length : novel?.total_chapters ?? 0;
  const currentEntry = chapters.find((item) => item.chapter_number === chapter.chapter_number);
  const label = currentEntry ? entryLabel(currentEntry) : `Chapter ${chapter.chapter_number}`;
  const heading = chapter.title || label;
  const showLabel = !heading.toLowerCase().startsWith(label.toLowerCase());
  const nextUnreadNumber = novel?.next_unread_chapter_number;
  const nextUnread = nextUnreadNumber != null && nextUnreadNumber !== nextEntry?.chapter_number && nextUnreadNumber !== chapter.chapter_number ? nextUnreadNumber : null;
  const paged = layout === "paged";
  const minutesLeft = words ? Math.max(1, Math.ceil((words * (1 - percent / 100)) / WORDS_PER_MINUTE)) : null;
  const storyHref = `/library/${library_id}/novels/${novel_id}`;
  const chapterHref = (n: number) => `/library/${library_id}/novels/${novel_id}/${n}`;

  const moreItems: MenuItem[] = [
    { label: "Search this chapter", icon: <Search aria-hidden="true" />, onSelect: openChapterSearch, hint: "Ctrl/⌘ F" },
    { label: "Add note", icon: <NotebookPen aria-hidden="true" />, onSelect: openNote },
    { label: "Copy quote", icon: <Quote aria-hidden="true" />, onSelect: () => void copyQuote() },
    { label: `Bookmarks and notes${annotations.length ? ` (${annotations.length})` : ""}`, icon: <StickyNote aria-hidden="true" />, onSelect: () => setAnnotationsOpen(true) },
    { label: "Chapter versions", icon: <ScrollText aria-hidden="true" />, onSelect: () => { setVersionAnchor(null); setVersionChapter(chapter_number); setVersionChapterKey(loadedChapterIdentity?.chapter_key); setVersionsOpen(true); } },
    { label: "Recap so far", icon: <ScrollText aria-hidden="true" />, onSelect: () => void openRecap() },
    { type: "separator" },
    { label: "Translation & story companion", icon: <BookOpenText aria-hidden="true" />, onSelect: () => {
      setToolsPassage(variant === "original" ? passageAnchor.current : null); setToolsOpen(true);
    } },
    { label: "Save chapter offline", icon: <HardDriveDownload aria-hidden="true" />, onSelect: () => void keepChapterOffline() },
    { label: "Download EPUB", icon: <Download aria-hidden="true" />, onSelect: () => void downloadEpub() },
    { label: "Export notes and progress", icon: <FileJson aria-hidden="true" />, onSelect: exportReadingState },
    { type: "separator" },
    { label: "Keyboard shortcuts", icon: <Keyboard aria-hidden="true" />, onSelect: () => setShortcutsOpen(true), hint: "?" },
    { label: "Back to story", icon: <BookOpenText aria-hidden="true" />, onSelect: () => navigate(storyHref) },
  ];

  const barFocusProps = {
    onFocus: () => setBarsFocused(true),
    onBlur: (event: React.FocusEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setBarsFocused(false);
    },
  };

  return (
    <div
      className={`reader${paged ? " reader--paged" : ""}${barsHidden ? " reader--bars-hidden" : ""}${listenOpen ? " reader--listening" : ""}`}
      data-reader-theme={readerTheme}
      data-paragraphs={t.paragraphStyle}
    >
      <header className="reader__top" {...barFocusProps}>
        <ReaderTopBar
          storyTitle={storyTitle}
          chapterTitle={heading}
          chapterLine={`${storyTitle} · ${label}`}
          backTo={storyHref}
          compact={compact}
          bookmarked={Boolean(chapterBookmark)}
          listening={listenOpen}
          onChapters={() => setDrawerOpen(true)}
          onBookmark={toggleBookmark}
          onListen={() => { capturePlace(); setListenOpen((value) => !value); }}
          chaptersRef={chaptersButtonRef}
          moreItems={moreItems}
          settings={(
            <ReaderSettingsControl
              open={settingsOpen}
              onOpenChange={value => { capturePlace(); setSettingsOpen(value); }}
              compact={compact}
              typography={t}
              resolvedTheme={readerTheme}
              appTheme={appTheme === "dark" ? "night" : "paper"}
              onChange={(key, value) => typo.set(key, value)}
              layout={layout}
              onLayout={changeLayout}
              authorNotes={authorNotes}
              onAuthorNotes={changeAuthorNotes}
              storyOnly={typo.storyOnly}
              onStoryOnly={typo.setStoryOnly}
              onUseForAll={typo.useForAllStories}
              sync={typo.sync}
              onResolveSync={typo.resolveSync}
            />
          )}
        />
      </header>

      <div
        ref={contentRef}
        className="reader__content"
        aria-busy={!restoredPosition || !readerAssetsReady}
        style={{ ...typographyStyle(t), ...paging.pagedStyle, visibility: restoredPosition && readerAssetsReady ? "visible" : "hidden" }}
        onPointerDownCapture={() => { selectedPassage.current = null; }}
        onClick={paging.onContentClick}
      >
        <article className="reader__text" aria-labelledby="reader-chapter-title">
          <OfflineBadge novelId={novel_id} chapterNumber={chapter.chapter_number} />
          {error && <Banner tone="warning">{error}</Banner>}
          {!!chapter.document?.image_assets?.missing && <Banner tone="warning">{chapter.document.image_assets.missing} {chapter.document.image_assets.missing === 1 ? "illustration could" : "illustrations could"} not be saved for offline reading. The text is available.{chapter.source_url ? " Use the chapter’s source link to view missing images." : " The source may still have the missing images."}</Banner>}
          {locatorReview && <Banner tone="warning" action={<button type="button" onClick={() => void acceptLocatedPosition()}>Keep this location</button>}>{savedChapterPlaceNeedsReview(progress,chapter) ? "The earlier saved place cannot be verified for this chapter identity. Automatic saves are paused; your earlier place is preserved until you choose a location." : "The saved passage is missing or has several matches in this text or view. Showing an approximate location. Automatic saves are paused; your earlier anchor is preserved."}</Banner>}
          {progressConflict && <Banner tone="warning" action={<>
            {chapterIdentityConflict && <Link to={`${storyHref}?tab=chapters`}>Review current chapters</Link>}
            {progressConflictCode === "content_changed" && <button type="button" onClick={() => window.location.reload()}>Reload revised text</button>}
            {(progressConflictCode === "reading_run_changed" || chapterIdentityConflict) && <button type="button" onClick={exportReadingState}>Download unsynchronized position</button>}
            <button type="button" onClick={() => void reconcileProgress("server")}>{progressConflictCode === "reading_run_changed" ? "Discard this queued position and use the current reading session" : "Use synced position"}</button>
            {progressConflictCode !== "reading_run_changed" && !chapterIdentityConflict && <button type="button" onClick={() => void reconcileProgress("device")}>Keep this device’s position</button>}
          </>}>{chapterIdentityConflict ? "The chapter list changed or this device’s saved place predates chapter identity checks. Automatic saves are paused. Your original unsynchronized anchor is kept; review the story’s current chapter list before accepting a new location." : progressConflictCode === "reading_run_changed" ? "A different reading session is active. Your unsynchronized position belongs to an earlier session and cannot overwrite the new one. Download it before discarding it if you want to keep a copy." : progressConflictCode === "content_changed" ? "This chapter changed since your saved position. Reload to review the revised text before choosing a position; your earlier anchor is retained." : "Another device changed your place. Choose which position to keep; both saves are retained until you choose."}</Banner>}
          {showLabel && <p className="reader__chapter-label">{label}</p>}
          <h1 id="reader-chapter-title" tabIndex={-1}>{heading}</h1>
          <PreviouslyOn novelId={novel_id} progress={progress} chapter={chapter} />
          {translation && <Banner tone="info" action={<>
            <button type="button" disabled={!chapter.document} onClick={() => { capturePlace(); setParallelText((value) => !value); }}>{parallelText ? "Translation only" : "Original alongside"}</button>
            <button type="button" onClick={() => { capturePlace(); setTranslation(null); }}>Read original</button>
          </>}>Translated into {translation.language}. Your original chapter is preserved.</Banner>}
          {pairedDocument ? <div className="reader-parallel-text"><ChapterBody content={pairedDocument.plain_text} authorNotes={authorNotes} document={pairedDocument} /></div>
            : <ChapterBody content={translation?.document.plain_text ?? chapter.content} authorNotes={authorNotes} document={translation?.document ?? chapter.document} />}
          {(nextEntry || navigationLive) ? <ReaderEndOfChapter
            chapterNumber={chapter.chapter_number}
            next={nextEntry ? { chapter_number: nextEntry.chapter_number, title: nextEntry.title, label: entryLabel(nextEntry) } : null}
            nextUnread={nextUnread}
            chapterHref={chapterHref}
            storyHref={storyHref}
          /> : <nav className="reader-end" aria-label="End of chapter"><p>End of chapter {chapter.chapter_number}</p><p>{navigationKnown ? "The saved chapter index ends here. Connect to check for newer chapters." : "The next chapter could not be verified. Open the chapter list or story to choose where to continue."}</p><Link to={storyHref}>Back to story</Link></nav>}
          <ChapterSourceLink site={novel?.novel_site ?? null} href={chapter.source_url ?? null} />
        </article>
      </div>

      <footer className="reader__bottom" {...barFocusProps}>
        <ListenPlayer
          chapter={chapter}
          libraryId={library_id}
          novelId={novel_id}
          audioCreationHref={`/library/${library_id}/novels/${novel_id}?tab=audio`}
          open={listenOpen}
          rendition={variant}
          readingLocator={()=>contentRef.current ? visibleBlockLocator(contentRef.current,layout==="paged") : undefined}
          onReadPassage={readAudioPassage}
          onAudioPassage={saveAudioPassage}
          onPlayingChange={setAudioPlaying}
          requestedChapterNumber={chapter_number}
          navigationKey={location.key}
          chapterReady={!loading && chapter.chapter_number === chapter_number}
          nextChapterNumber={nextEntry?.chapter_number}
          onNextChapter={nextChapter}
          onClose={() => setListenOpen(false)}
        />
        <ReaderBottomBar
          chapterNumber={chapter.chapter_number}
          totalChapters={totalChapters}
          chapterOrdinal={indexKind === "live" ? indexedNeighbors.ordinal : null}
          percent={percent}
          minutesLeft={minutesLeft}
          paged={paged}
          page={paging.page}
          pageCount={paging.pageCount}
          hasPrevious={!!previousEntry}
          hasNext={!!nextEntry}
          onPrevious={previousChapter}
          onNext={nextChapter}
          onPreviousPage={() => paging.goToPage(paging.page - 1)}
          onNextPage={() => paging.goToPage(paging.page + 1)}
        />
      </footer>

      <ChapterDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        novelId={novel_id}
        chapters={chapters}
        currentChapter={chapter.chapter_number}
        lastReadChapter={progress?.chapter_number ?? null}
        loading={chaptersLoading}
        error={chaptersError}
        onSelect={goToChapter}
      />
      <NoteDialog
        open={noteQuote !== null}
        quote={noteQuote ?? ""}
        onClose={() => setNoteQuote(null)}
        onSave={(note) => { const quote = noteQuote ?? ""; const anchor = noteLocator.current || undefined; setNoteQuote(null); void addAnnotation("note", note, quote, anchor); }}
      />
      <AnnotationsSheet
        open={annotationsOpen}
        onClose={() => setAnnotationsOpen(false)}
        annotations={annotations}
        chapterNumber={chapter.chapter_number} chapterKey={loadedChapterIdentity?.chapter_key}
        onJump={jumpToAnnotation}
        onDelete={(id) => void removeAnnotation(id)}
        onViewVersion={(annotation) => {
          if (!annotation.locator_content_version || annotation.chapter_number == null) return;
          setAnnotationsOpen(false);
          setVersionChapter(annotation.chapter_number);
          setVersionChapterKey((annotation as ReadingAnnotation & {chapter_key?:string}).chapter_key);
          setVersionAnchor({ version: annotation.locator_content_version, locator: savedLocator(annotation) });
          setVersionsOpen(true);
        }}
      />
      <RecapSheet open={recapOpen} onClose={() => setRecapOpen(false)} recap={recap} loading={recapLoading} history={readingHistory} hiatus={hiatus} />
      <ChapterVersionsSheet open={versionsOpen} onClose={() => setVersionsOpen(false)} novelId={novel_id} chapter={versionChapter} expectedChapterKey={versionChapterKey} requested={versionAnchor} />
      <ChapterSearchSheet open={searchOpen} onClose={() => setSearchOpen(false)} blocks={searchBlocks} onJump={jumpSearchMatch} />
      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} enabled={shortcutsEnabled} onEnabled={changeShortcuts} />
      <ReaderToolsSheet open={toolsOpen} onClose={() => setToolsOpen(false)} novelId={novel_id} chapter={chapter_number}
        libraryId={library_id} identity={loadedChapterIdentity} sourceVersion={chapterSourceVersion(chapter)} readingRunKey={progress?.reading_run_key ?? null} passage={toolsPassage} onTranslation={variant => {
          if (variant && chapter.document?.content_version && variant.source_version !== chapter.document.content_version) {
            addToast("This translation belongs to an earlier text version. Export it, or translate the current chapter.", "info");
            return;
          }
          capturePlace(); setTranslation(variant);
        }} />
    </div>
  );
};

export default Reader;
