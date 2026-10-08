import React, { useEffect, useMemo, useState } from "react";
import { organizationService } from "../../services/organizationService";

export interface DrawerChapter {
  chapter_number: number;
  title: string;
  category?: string;
}

interface ChapterDrawerProps {
  open: boolean;
  onClose: () => void;
  novelId: number;
  chapters: DrawerChapter[];
  currentChapter: number;
  onSelect: (chapterNumber: number) => void;
}

const DEFAULT_CATEGORIES = ["story"];

const categoryLabel = (category: string) =>
  category.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());

/** Drawer listing every chapter; non-followed categories sit behind a toggle. */
const ChapterDrawer: React.FC<ChapterDrawerProps> = ({ open, onClose, novelId, chapters, currentChapter, onSelect }) => {
  const [followed, setFollowed] = useState<string[]>(DEFAULT_CATEGORIES);
  const [showOther, setShowOther] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    organizationService.getPersonal(novelId)
      .then((data) => {
        const categories = (data as { followed_categories?: string[] }).followed_categories;
        if (!cancelled && Array.isArray(categories)) setFollowed(categories.length ? categories : DEFAULT_CATEGORIES);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [open, novelId]);

  const groups = useMemo(() => {
    const byCategory = new Map<string, DrawerChapter[]>();
    [...chapters].sort((a, b) => a.chapter_number - b.chapter_number).forEach((chapter) => {
      const category = chapter.category || "story";
      byCategory.set(category, [...(byCategory.get(category) || []), chapter]);
    });
    return [...byCategory.entries()];
  }, [chapters]);

  if (!open) return null;

  const visibleGroups = groups.filter(([category]) => followed.includes(category));
  const hiddenCount = groups.filter(([category]) => !followed.includes(category)).reduce((sum, [, items]) => sum + items.length, 0);

  return (
    <div className="reader-chapter-drawer" role="dialog" aria-label="Chapter list">
      <div className="reader-chapter-drawer__header">
        <strong>Chapters</strong>
        <button type="button" onClick={onClose} aria-label="Close chapter list">×</button>
      </div>
      {visibleGroups.map(([category, items]) => (
        <section key={category} className="reader-chapter-drawer__group">
          <h3>{categoryLabel(category)}</h3>
          <ul>
            {items.map((chapter) => (
              <li key={chapter.chapter_number}>
                <button
                  type="button"
                  className={chapter.chapter_number === currentChapter ? "is-active" : ""}
                  onClick={() => { onSelect(chapter.chapter_number); onClose(); }}
                >
                  <span className="chapter-number">{chapter.chapter_number}</span>
                  <span className="chapter-title">{chapter.title || "Untitled"}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {hiddenCount > 0 && (
        <button type="button" className="reader-chapter-drawer__toggle" aria-expanded={showOther} onClick={() => setShowOther((value) => !value)}>
          {showOther ? "Hide" : "Show"} {hiddenCount} chapter{hiddenCount === 1 ? "" : "s"} in other categories
        </button>
      )}
      {showOther && groups.filter(([category]) => !followed.includes(category)).map(([category, items]) => (
        <section key={category} className="reader-chapter-drawer__group reader-chapter-drawer__group--other">
          <h3>{categoryLabel(category)}</h3>
          <ul>
            {items.map((chapter) => (
              <li key={chapter.chapter_number}>
                <button type="button" onClick={() => { onSelect(chapter.chapter_number); onClose(); }}>
                  <span className="chapter-number">{chapter.chapter_number}</span>
                  <span className="chapter-title">{chapter.title || "Untitled"}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
};

export default ChapterDrawer;
