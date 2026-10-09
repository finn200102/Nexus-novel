import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { BookOpenText, Download, FileJson, HardDriveDownload, Keyboard, NotebookPen, Quote, ScrollText, StickyNote } from "lucide-react";
import { chapterService } from "../services/chapterService";
import { novelService } from "../services/novelService";
import { offlineReaderStore } from "../services/offlineReaderStore";
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

interface ChapterContent {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
  source_url?: string | null;
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
  id: number;
  chapter_number: number;
  title: string;
  category?: string;
}

interface ReadingProgress {
  chapter_number: number | null;
  position: number;
  percent: number;
}

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
  const citationOffset = Number(searchParams.get("offset"));

  const [chapter, setChapter] = useState<ChapterContent | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  usePageTitle(chapter && novel ? `${chapter.title} · ${displayTitle(novel)}` : null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState<boolean>(true);
  const [chaptersError, setChaptersError] = useState<string | null>(null);
  const typo = useReaderTypography(novel_id);
  const t = typo.typography;
  const readerTheme = resolveReaderTheme(t.theme, appTheme);
  const [authorNotes, setAuthorNotes] = useState<AuthorNotesMode>(readAuthorNotesMode);
  const [layout, setLayout] = useState<ReaderLayout>(readLayout);
  const [shortcutsEnabled, setShortcutsEnabled] = useState(readShortcutsEnabled);
  const [progress, setProgress] = useState<ReadingProgress | null>(null);
  const [percent, setPercent] = useState(0);
  const [annotations, setAnnotations] = useState<ReadingAnnotation[]>([]);
  const [restoredPosition, setRestoredPosition] = useState(false);
  const [readingHistory, setReadingHistory] = useState<{ chapters_touched: number; active_days: number; current_streak_days: number } | null>(null);
  const [recap, setRecap] = useState<RecapData | null>(null);
  const [recapLoading, setRecapLoading] = useState(false);
  const [hiatus, setHiatus] = useState<{ state: string; confidence: number; reason: string } | null>(null);
  // Overlays
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [listenOpen, setListenOpen] = useState(false);
  const [noteQuote, setNoteQuote] = useState<string | null>(null);
  const [annotationsOpen, setAnnotationsOpen] = useState(false);
  const [recapOpen, setRecapOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [barsFocused, setBarsFocused] = useState(false);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const chaptersButtonRef = useRef<HTMLButtonElement | null>(null);

  // Reading fonts ship in their own CSS chunk, loaded only here.
  useEffect(() => { void import("../components/reader/readerFonts"); }, []);

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
    const fetchData = async () => {
      try {
        setLoading(true);
        const chapterData = await chapterService.getChapterContentByNumber(chapter_number, library_id, novel_id);
        const savedProgress = await chapterService.getReadingProgress(novel_id).catch(() => null);
        void novelService.getHiatusStatus(library_id, novel_id).then(setHiatus).catch(() => setHiatus(null));
        setChapter(chapterData);
        setProgress(savedProgress);
        setRestoredPosition(false);
        localStorage.setItem(`nexus-reader-chapter-${novel_id}-${chapter_number}`, JSON.stringify(chapterData));
        void offlineReaderStore.save(chapterData).catch(() => undefined);

        if (chapterData && chapterData.novel_id) {
          const novelData = await novelService.getNovelById(library_id, chapterData.novel_id);
          setNovel(novelData);
        }
        setError(null);
      } catch (err) {
        const offlineChapter = await offlineReaderStore.get(novel_id, chapter_number).catch(() => null);
        const cached = localStorage.getItem(`nexus-reader-chapter-${novel_id}-${chapter_number}`);
        if (offlineChapter || cached) {
          setChapter(offlineChapter || JSON.parse(cached!));
          setProgress(null);
          setError("Offline mode: showing the last cached copy.");
        } else {
          const detail = axios.isAxiosError(err) ? String(err.response?.data?.detail || "") : "";
          setError(detail === "Chapter content is not downloaded"
            ? "This chapter has not been downloaded yet. Queue it from the story page, then come back to read or listen."
            : "Couldn’t load this chapter. Check your connection and try again.");
        }
        console.error("Error fetching data:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [chapter_number, library_id, novel_id]);

  useEffect(() => {
    chapterService.getReadingAnnotations(novel_id)
      .then(setAnnotations)
      .catch((err) => console.error("Failed to load reader annotations", err));
  }, [novel_id]);

  useEffect(() => {
    void chapterService.getReadingHistory(novel_id).then(setReadingHistory).catch(() => setReadingHistory(null));
  }, [novel_id, chapter_number]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter || !progress || progress.chapter_number !== chapter.chapter_number) return;
    window.requestAnimationFrame(() => {
      if (layout === "paged") {
        const maxLeft = Math.max(content.scrollWidth - content.clientWidth, 0);
        const column = content.clientWidth || 1;
        content.scrollLeft = Math.round(((progress.percent / 100) * maxLeft) / column) * column;
      } else {
        content.scrollTop = progress.position || ((progress.percent / 100) * Math.max(content.scrollHeight - content.clientHeight, 0));
      }
      setRestoredPosition(true);
    });
  }, [chapter, progress, layout]);

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
    const fetchChapters = async () => {
      if (!novel_id) return;
      try {
        setChaptersLoading(true);
        const list = await chapterService.getChapters(novel_id);
        if (Array.isArray(list)) {
          setChapters([...list].sort((a, b) => a.chapter_number - b.chapter_number));
          setChaptersError(null);
        } else {
          setChapters([]);
        }
      } catch (err) {
        console.error("Failed to load chapter list", err);
        setChaptersError("Couldn’t load the chapter list.");
      } finally {
        setChaptersLoading(false);
      }
    };

    fetchChapters();
  }, [novel_id]);

  const goToChapter = useCallback((target: number) => {
    navigate(`/library/${library_id}/novels/${novel_id}/${target}`);
  }, [library_id, novel_id, navigate]);

  const paging = useReaderPaging({
    contentRef,
    paged: layout === "paged",
    layoutKey: `${chapter?.id ?? 0}-${t.width}-${t.fontSize}-${t.lineHeight}-${t.font}-${t.letterSpacing}-${t.wordSpacing}-${t.paragraphStyle}-${compact}-${listenOpen}`,
    onPreviousChapter: () => goToChapter(chapter_number - 1),
    onNextChapter: () => goToChapter(chapter_number + 1),
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
      frame = window.requestAnimationFrame(() => setPercent(value));
      if (!paged) {
        const delta = content.scrollTop - lastTop;
        if (delta > 12 && content.scrollTop > 120 && value < 98) setChromeHidden(true);
        else if (delta < -12 || value >= 98) setChromeHidden(false);
        lastTop = content.scrollTop;
      }
      window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        chapterService.updateReadingProgress(novel_id, chapter.chapter_number, Math.round(offset), value)
          .catch((err) => console.error("Failed to save reading progress", err));
      }, 500);
    };
    content.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      content.removeEventListener("scroll", onScroll);
      window.clearTimeout(timeout);
      window.cancelAnimationFrame(frame);
    };
  }, [chapter, novel_id, restoredPosition, layout, setChromeHidden]);

  useEffect(() => { setChromeHidden(false); setPercent(0); }, [chapter?.id, layout, setChromeHidden]);
  useReadingHeartbeat(novel_id, chapter?.id);

  const changeAuthorNotes = (mode: AuthorNotesMode) => { setAuthorNotes(mode); writeAuthorNotesMode(mode); };
  const changeLayout = (next: ReaderLayout) => { setLayout(next); writeLayout(next); };
  const changeShortcuts = (enabled: boolean) => { setShortcutsEnabled(enabled); writeShortcutsEnabled(enabled); };

  const addAnnotation = useCallback(async (annotationType: "bookmark" | "note", note?: string, quote?: string) => {
    if (!chapter || !contentRef.current) return;
    const content = contentRef.current;
    const value = layout === "paged"
      ? scrollPercent(content.scrollLeft, content.scrollWidth - content.clientWidth)
      : scrollPercent(content.scrollTop, content.scrollHeight - content.clientHeight);
    const selection = quote ?? (window.getSelection()?.toString().trim() || "");
    try {
      const created = await chapterService.createReadingAnnotation(novel_id, {
        chapter_number: chapter.chapter_number,
        annotation_type: annotationType,
        position: Math.round(layout === "paged" ? content.scrollLeft : content.scrollTop),
        percent: value,
        quote: selection || undefined,
        note: note || undefined,
      });
      setAnnotations((current) => [created, ...current]);
      addToast(annotationType === "bookmark" ? "Bookmarked." : "Note saved.", "success");
    } catch (err) {
      console.error("Failed to save reader annotation", err);
      addToast(annotationType === "bookmark" ? "Couldn’t save the bookmark." : "Couldn’t save the note.", "error");
    }
  }, [chapter, novel_id, layout, addToast]);

  const removeAnnotation = useCallback(async (id: number) => {
    try {
      await chapterService.deleteReadingAnnotation(id);
      setAnnotations((current) => current.filter((annotation) => annotation.id !== id));
    } catch {
      addToast("Couldn’t delete it. Try again.", "error");
    }
  }, [addToast]);

  const chapterBookmark = annotations.find((a) => a.chapter_number === chapter_number && a.annotation_type === "bookmark");
  const toggleBookmark = useCallback(() => {
    if (chapterBookmark) {
      void removeAnnotation(chapterBookmark.id).then(() => addToast("Bookmark removed."));
    } else {
      void addAnnotation("bookmark");
    }
  }, [chapterBookmark, removeAnnotation, addAnnotation, addToast]);

  const jumpToAnnotation = (annotation: ReadingAnnotation) => {
    setAnnotationsOpen(false);
    if (annotation.chapter_number !== chapter_number) { goToChapter(annotation.chapter_number); return; }
    const content = contentRef.current;
    if (!content) return;
    if (layout === "paged") paging.goToPage(Math.round((annotation.percent / 100) * (paging.pageCount - 1)));
    else content.scrollTop = (annotation.percent / 100) * Math.max(content.scrollHeight - content.clientHeight, 0);
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
    const payload = { exported_at: new Date().toISOString(), novel_id, novel_title: novel?.title, progress, annotations };
    download(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }), `nexus-reading-state-${novel_id}.json`);
  };

  const copyQuote = async () => {
    const quote = window.getSelection()?.toString().trim();
    if (!quote) { addToast("Select some text in the chapter first, then choose Copy quote."); return; }
    const payload = `“${quote}”\n— ${novel?.title || "Nexus"}, chapter ${chapter?.chapter_number || ""}`;
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

  const openNote = () => setNoteQuote(window.getSelection()?.toString().trim() || "");

  const next = () => (layout === "paged" ? paging.advance(1) : goToChapter(chapter_number + 1));
  const previous = () => (layout === "paged" ? paging.advance(-1) : goToChapter(chapter_number - 1));
  const anyOverlay = drawerOpen || settingsOpen || noteQuote !== null || annotationsOpen || recapOpen || shortcutsOpen;
  useReaderShortcuts({
    next: () => { if (!anyOverlay && chapter && (layout === "paged" || chapter_number < (novel?.total_chapters ?? Infinity))) next(); },
    previous: () => { if (!anyOverlay && chapter && (layout === "paged" || chapter_number > 1)) previous(); },
    bookmark: () => { if (!anyOverlay) toggleBookmark(); },
    chapters: () => setDrawerOpen(true),
    textSettings: () => setSettingsOpen(true),
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
  const totalChapters = novel?.total_chapters ?? Math.max(chapters.length, chapter.chapter_number);
  const currentEntry = chapters.find((item) => item.chapter_number === chapter.chapter_number);
  const label = currentEntry ? entryLabel(currentEntry) : `Chapter ${chapter.chapter_number}`;
  const heading = chapter.title || label;
  const showLabel = !heading.toLowerCase().startsWith(label.toLowerCase());
  const nextEntry = chapters.find((item) => item.chapter_number === chapter.chapter_number + 1)
    ?? (chapter.chapter_number < totalChapters ? { chapter_number: chapter.chapter_number + 1, title: "" } : null);
  const nextUnread = novel?.next_unread_chapter_number && novel.next_unread_chapter_number !== chapter.chapter_number + 1 && novel.next_unread_chapter_number !== chapter.chapter_number
    ? novel.next_unread_chapter_number : null;
  const paged = layout === "paged";
  const minutesLeft = words ? Math.max(1, Math.ceil((words * (1 - percent / 100)) / WORDS_PER_MINUTE)) : null;
  const barsHidden = paging.chromeHidden && !barsFocused && !anyOverlay && !listenOpen;
  const storyHref = `/library/${library_id}/novels/${novel_id}`;
  const chapterHref = (n: number) => `/library/${library_id}/novels/${novel_id}/${n}`;

  const moreItems: MenuItem[] = [
    { label: "Add note", icon: <NotebookPen aria-hidden="true" />, onSelect: openNote },
    { label: "Copy quote", icon: <Quote aria-hidden="true" />, onSelect: () => void copyQuote() },
    { label: `Bookmarks and notes${annotations.length ? ` (${annotations.length})` : ""}`, icon: <StickyNote aria-hidden="true" />, onSelect: () => setAnnotationsOpen(true) },
    { label: "Recap so far", icon: <ScrollText aria-hidden="true" />, onSelect: () => void openRecap() },
    { type: "separator" },
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
          onListen={() => setListenOpen((value) => !value)}
          chaptersRef={chaptersButtonRef}
          moreItems={moreItems}
          settings={(
            <ReaderSettingsControl
              open={settingsOpen}
              onOpenChange={setSettingsOpen}
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
            />
          )}
        />
      </header>

      <div
        ref={contentRef}
        className="reader__content"
        style={{ ...typographyStyle(t), ...paging.pagedStyle }}
        onClick={paging.onContentClick}
      >
        <article className="reader__text" aria-labelledby="reader-chapter-title">
          <OfflineBadge novelId={novel_id} chapterNumber={chapter.chapter_number} />
          {error && <Banner tone="warning">{error}</Banner>}
          {showLabel && <p className="reader__chapter-label">{label}</p>}
          <h1 id="reader-chapter-title" tabIndex={-1}>{heading}</h1>
          <PreviouslyOn novelId={novel_id} progress={progress} chapter={chapter} />
          <ChapterBody content={chapter.content} authorNotes={authorNotes} />
          <ReaderEndOfChapter
            chapterNumber={chapter.chapter_number}
            next={nextEntry ? { chapter_number: nextEntry.chapter_number, title: nextEntry.title, label: entryLabel(nextEntry) } : null}
            nextUnread={nextUnread}
            chapterHref={chapterHref}
            storyHref={storyHref}
          />
          <ChapterSourceLink site={novel?.novel_site ?? null} href={chapter.source_url ?? null} />
        </article>
      </div>

      <footer className="reader__bottom" {...barFocusProps}>
        <ListenPlayer
          chapter={chapter}
          libraryId={library_id}
          novelId={novel_id}
          open={listenOpen}
          onClose={() => setListenOpen(false)}
        />
        <ReaderBottomBar
          chapterNumber={chapter.chapter_number}
          totalChapters={totalChapters}
          percent={percent}
          minutesLeft={minutesLeft}
          paged={paged}
          page={paging.page}
          pageCount={paging.pageCount}
          hasPrevious={chapter.chapter_number > 1}
          hasNext={chapter.chapter_number < totalChapters}
          onPrevious={() => goToChapter(chapter.chapter_number - 1)}
          onNext={() => goToChapter(chapter.chapter_number + 1)}
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
        onSave={(note) => { const quote = noteQuote ?? ""; setNoteQuote(null); void addAnnotation("note", note, quote); }}
      />
      <AnnotationsSheet
        open={annotationsOpen}
        onClose={() => setAnnotationsOpen(false)}
        annotations={annotations}
        chapterNumber={chapter.chapter_number}
        onJump={jumpToAnnotation}
        onDelete={(id) => void removeAnnotation(id)}
      />
      <RecapSheet open={recapOpen} onClose={() => setRecapOpen(false)} recap={recap} loading={recapLoading} history={readingHistory} hiatus={hiatus} />
      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} enabled={shortcutsEnabled} onEnabled={changeShortcuts} />
    </div>
  );
};

export default Reader;
