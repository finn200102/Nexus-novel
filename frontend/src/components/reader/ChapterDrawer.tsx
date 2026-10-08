import React, { useEffect, useMemo, useRef, useState } from "react";
import { HardDriveDownload } from "lucide-react";
import { Button, Input, Sheet } from "../ui";
import { organizationService } from "../../services/organizationService";
import { offlineReaderStore } from "../../services/offlineReaderStore";
import { categoryLabel, entryLabel, matchesChapter } from "./chapterLabels";

import type { DrawerChapter } from "./chapterLabels";

// Shared with the story page's chapter list (D9).
export type { DrawerChapter } from "./chapterLabels";
// eslint-disable-next-line react-refresh/only-export-components
export { categoryLabel, entryLabel, matchesChapter } from "./chapterLabels";

interface ChapterDrawerProps {
  open: boolean;
  onClose: () => void;
  novelId: number;
  chapters: DrawerChapter[];
  currentChapter: number;
  /** Last chapter with saved progress; later chapters get an unread dot. */
  lastReadChapter?: number | null;
  loading?: boolean;
  error?: string | null;
  onSelect: (chapterNumber: number) => void;
}

const DEFAULT_CATEGORIES = ["story"];

/**
 * Chapters panel (left drawer on desktop, bottom sheet on phones): search, full titles,
 * unread dot, saved-offline icon, current chapter scrolled into view. Categories the reader
 * doesn't follow (side stories, indexes …) sit behind a toggle.
 */
const ChapterDrawer: React.FC<ChapterDrawerProps> = ({ open, onClose, novelId, chapters, currentChapter, lastReadChapter, loading, error, onSelect }) => {
  const [followed, setFollowed] = useState<string[]>(DEFAULT_CATEGORIES);
  const [showOther, setShowOther] = useState(false);
  const [query, setQuery] = useState("");
  const [offline, setOffline] = useState<Set<number>>(new Set());
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    organizationService.getPersonal(novelId)
      .then((data) => {
        const categories = (data as { followed_categories?: string[] }).followed_categories;
        if (!cancelled && Array.isArray(categories)) setFollowed(categories.length ? categories : DEFAULT_CATEGORIES);
      })
      .catch(() => undefined);
    offlineReaderStore.listForNovel(novelId)
      .then((items) => { if (!cancelled) setOffline(new Set(items.map((item) => item.chapter_number))); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [open, novelId]);

  // Bring the current chapter into view once the list has rendered.
  useEffect(() => {
    if (!open || loading) return;
    const frame = window.requestAnimationFrame(() => {
      listRef.current?.querySelector("[aria-current='true']")?.scrollIntoView?.({ block: "center" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, loading, chapters.length]);

  const groups = useMemo(() => {
    const byCategory = new Map<string, DrawerChapter[]>();
    [...chapters].sort((a, b) => a.chapter_number - b.chapter_number).forEach((chapter) => {
      const category = chapter.category || "story";
      byCategory.set(category, [...(byCategory.get(category) || []), chapter]);
    });
    return [...byCategory.entries()];
  }, [chapters]);

  const searching = query.trim() !== "";
  const visibleGroups = groups
    .filter(([category]) => searching || showOther || followed.includes(category))
    .map(([category, items]) => [category, items.filter((item) => matchesChapter(item, query))] as const)
    .filter(([, items]) => items.length > 0);
  const hiddenCount = groups.filter(([category]) => !followed.includes(category)).reduce((sum, [, items]) => sum + items.length, 0);
  const showHeadings = visibleGroups.length > 1 || (visibleGroups[0] && visibleGroups[0][0] !== "story");

  const select = (chapterNumber: number) => { onSelect(chapterNumber); onClose(); };

  return (
    <Sheet open={open} onClose={onClose} title="Chapters" side="left" className="reader-chapters" initialFocus={searchRef} closeLabel="Close chapters">
      <Input
        ref={searchRef}
        search
        label="Find chapter"
        hideLabel
        placeholder="Find chapter by number or title"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onClear={() => setQuery("")}
      />
      <div ref={listRef} className="reader-chapters__list">
        {loading && <p className="text-muted">Loading chapters…</p>}
        {error && <p role="alert">{error}</p>}
        {!loading && !error && visibleGroups.length === 0 && (
          <p className="text-muted">{searching ? `No chapter matches “${query.trim()}”.` : "No chapters yet."}</p>
        )}
        {visibleGroups.map(([category, items]) => (
          <section key={category} className="reader-chapters__group">
            {showHeadings && <h3>{categoryLabel(category)}</h3>}
            <ul>
              {items.map((chapter) => {
                const current = chapter.chapter_number === currentChapter;
                const unread = !current && lastReadChapter != null && chapter.chapter_number > lastReadChapter;
                const saved = offline.has(chapter.chapter_number);
                return (
                  <li key={chapter.chapter_number}>
                    <button
                      type="button"
                      className="reader-chapters__item"
                      aria-current={current ? "true" : undefined}
                      onClick={() => select(chapter.chapter_number)}
                    >
                      <span className="reader-chapters__label">{entryLabel(chapter)}</span>
                      <span className="reader-chapters__title">{chapter.title || "Untitled"}</span>
                      <span className="reader-chapters__meta">
                        {unread && <span className="reader-chapters__dot" title="Unread"><span className="visually-hidden">Unread</span></span>}
                        {saved && <HardDriveDownload aria-label="Saved offline" role="img" size={16} />}
                        {current && <span className="visually-hidden">(current chapter)</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
        {!searching && hiddenCount > 0 && (
          <Button variant="ghost" size="sm" aria-expanded={showOther} onClick={() => setShowOther((value) => !value)}>
            {showOther ? "Hide" : "Show"} {hiddenCount} chapter{hiddenCount === 1 ? "" : "s"} in other categories
          </Button>
        )}
      </div>
    </Sheet>
  );
};

export default ChapterDrawer;
