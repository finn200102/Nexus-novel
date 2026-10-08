export interface DrawerChapter {
  chapter_number: number;
  title: string;
  category?: string;
}

export const categoryLabel = (category: string) =>
  category.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());

/** "Chapter 41" for story chapters; non-chapter entries (index, contents …) are labelled by their kind. */
export const entryLabel = (chapter: DrawerChapter) =>
  !chapter.category || chapter.category === "story" ? `Chapter ${chapter.chapter_number}` : categoryLabel(chapter.category);

export const matchesChapter = (chapter: DrawerChapter, query: string) => {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return String(chapter.chapter_number) === q || String(chapter.chapter_number).startsWith(q) || (chapter.title || "").toLowerCase().includes(q);
};

