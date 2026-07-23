import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { chapterService } from "../services/chapterService";
import { novelService } from "../services/novelService";
import "../styles/Reader.css";

interface ChapterContent {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
}

interface Novel {
  id: number;
  title: string;
  author: string;
  library_id: number;
  total_chapters: number;
}

interface ChapterSummary {
  id: number;
  chapter_number: number;
  title: string;
}

interface ReadingProgress {
  chapter_number: number | null;
  position: number;
  percent: number;
}

interface ReadingAnnotation {
  id: number;
  chapter_number: number;
  annotation_type: "bookmark" | "note" | "highlight";
  position: number;
  percent: number;
  quote?: string | null;
  note?: string | null;
}

const themeOptions: { value: "night" | "dusk" | "paper"; label: string }[] = [
  { value: "night", label: "Night" },
  { value: "dusk", label: "Dusk" },
  { value: "paper", label: "Paper" },
];

const Reader: React.FC = () => {
  const { libraryId, novelId, chapterNumber } = useParams<{
    libraryId: string;
    novelId: string;
    chapterNumber: string;
  }>();
  const navigate = useNavigate();

  const chapter_number = Number(chapterNumber);
  const library_id = Number(libraryId);
  const novel_id = Number(novelId);

  const [chapter, setChapter] = useState<ChapterContent | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState<boolean>(true);
  const [chaptersError, setChaptersError] = useState<string | null>(null);
  const [fontScale, setFontScale] = useState(() => Number(localStorage.getItem("nexus-reader-font-scale")) || 1);
  const [theme, setTheme] = useState<"night" | "dusk" | "paper">(() => (localStorage.getItem("nexus-reader-theme") as "night" | "dusk" | "paper") || "night");
  const [progress, setProgress] = useState<ReadingProgress | null>(null);
  const [annotations, setAnnotations] = useState<ReadingAnnotation[]>([]);
  const [restoredPosition, setRestoredPosition] = useState(false);
  const contentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [chapterData, savedProgress] = await Promise.all([
          chapterService.getChapterContentByNumber(chapter_number, library_id, novel_id),
          chapterService.getReadingProgress(novel_id),
        ]);
        setChapter(chapterData);
        setProgress(savedProgress);
        setRestoredPosition(false);

        if (chapterData && chapterData.novel_id) {
          const novelData = await novelService.getNovelById(
            library_id,
            chapterData.novel_id
          );
          setNovel(novelData);
        }
        setError(null);
      } catch (err) {
        setError("Failed to load content. Please try again later.");
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
    localStorage.setItem("nexus-reader-font-scale", String(fontScale));
  }, [fontScale]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-theme", theme);
  }, [theme]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter || !progress || progress.chapter_number !== chapter.chapter_number) return;
    window.requestAnimationFrame(() => {
      content.scrollTop = progress.position || ((progress.percent / 100) * Math.max(content.scrollHeight - content.clientHeight, 0));
      setRestoredPosition(true);
    });
  }, [chapter, progress]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.key === "ArrowLeft") goToChapter(chapter_number - 1);
      if (event.key === "ArrowRight") goToChapter(chapter_number + 1);
      if (event.key.toLowerCase() === "b") void addAnnotation("bookmark");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [chapter_number]);

  useEffect(() => {
    const fetchChapters = async () => {
      if (!novel_id) return;
      try {
        setChaptersLoading(true);
        const list = await chapterService.getChapters(novel_id);
        if (Array.isArray(list)) {
          const sorted = [...list].sort(
            (a, b) => a.chapter_number - b.chapter_number
          );
          setChapters(sorted);
          setChaptersError(null);
        } else {
          setChapters([]);
        }
      } catch (err) {
        console.error("Failed to load chapter list", err);
        setChaptersError("Unable to load chapters");
      } finally {
        setChaptersLoading(false);
      }
    };

    fetchChapters();
  }, [novel_id]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter) return;
    let timeout: number | undefined;
    const saveProgress = () => {
      const maxScroll = Math.max(content.scrollHeight - content.clientHeight, 1);
      const percent = Math.min(100, Math.max(0, (content.scrollTop / maxScroll) * 100));
      window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        chapterService.updateReadingProgress(
          novel_id,
          chapter.chapter_number,
          Math.round(content.scrollTop),
          percent
        ).catch((err) => console.error("Failed to save reading progress", err));
      }, 500);
    };
    content.addEventListener("scroll", saveProgress, { passive: true });
    return () => {
      content.removeEventListener("scroll", saveProgress);
      window.clearTimeout(timeout);
    };
  }, [chapter, novel_id, restoredPosition]);

  const goToChapter = (target: number) => {
    navigate(`/library/${library_id}/novels/${novel_id}/${target}`);
  };

  const decreaseFont = () => setFontScale((prev) => Math.max(0.85, prev - 0.1));
  const increaseFont = () => setFontScale((prev) => Math.min(1.3, prev + 0.1));

  const addAnnotation = async (annotationType: "bookmark" | "note") => {
    if (!chapter || !contentRef.current) return;
    const content = contentRef.current;
    const maxScroll = Math.max(content.scrollHeight - content.clientHeight, 1);
    const percent = Math.min(100, Math.max(0, (content.scrollTop / maxScroll) * 100));
    const selection = window.getSelection()?.toString().trim() || "";
    const note = annotationType === "note" ? window.prompt("Private note (optional)") : null;
    if (annotationType === "note" && note === null) return;
    try {
      const created = await chapterService.createReadingAnnotation(novel_id, {
        chapter_number: chapter.chapter_number,
        annotation_type: annotationType,
        position: Math.round(content.scrollTop),
        percent,
        quote: selection || undefined,
        note: note || undefined,
      });
      setAnnotations((current) => [created, ...current]);
    } catch (err) {
      console.error("Failed to save reader annotation", err);
    }
  };

  const removeAnnotation = async (id: number) => {
    await chapterService.deleteReadingAnnotation(id);
    setAnnotations((current) => current.filter((annotation) => annotation.id !== id));
  };

  if (loading) return <div className="reader-loading">Loading content...</div>;
  if (error) return <div className="reader-error">{error}</div>;
  if (!chapter || !novel)
    return <div className="reader-not-found">Content not found</div>;

  const readerClass = `reader-shell reader-shell--${theme}`;

  return (
    <div className={readerClass}>
      <aside className="reader-sidebar">
        <div className="reader-sidebar__header">
          <p>Chapters</p>
          <span>
            {chapter.chapter_number}/{novel.total_chapters}
          </span>
        </div>
        <div className="reader-sidebar__list">
          {chaptersLoading && (
            <p className="reader-sidebar__status">Loading…</p>
          )}
          {chaptersError && (
            <p className="reader-sidebar__status reader-sidebar__status--error">
              {chaptersError}
            </p>
          )}
          {!chaptersLoading && !chaptersError && (
            <ul>
              {chapters.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={
                      item.chapter_number === chapter.chapter_number
                        ? "is-active"
                        : ""
                    }
                    onClick={() => goToChapter(item.chapter_number)}
                  >
                    <span className="chapter-number">{item.chapter_number}</span>
                    <span className="chapter-title">{item.title || "Untitled"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <article className="reader-body">
        <header className="reader-toolbar">
          <div>
            <p className="reader-toolbar__eyebrow">{novel.author}</p>
            <h1>{chapter.title}</h1>
            <span>Chapter {chapter.chapter_number}</span>
          </div>
          <div className="reader-toolbar__controls">
            <div className="reader-type-controls">
              <button type="button" onClick={decreaseFont}>
                A-
              </button>
              <button type="button" onClick={increaseFont}>
                A+
              </button>
            </div>
            <div className="reader-type-controls">
              <button type="button" onClick={() => void addAnnotation("bookmark")} title="Bookmark current position">Bookmark</button>
              <button type="button" onClick={() => void addAnnotation("note")} title="Add a private note">Note</button>
            </div>
            <div className="reader-theme-controls">
              {themeOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={theme === option.value ? "is-active" : ""}
                  onClick={() => setTheme(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        <div
          ref={contentRef}
          className="reader-content"
          style={{ fontSize: `${1.05 * fontScale}rem` }}
        >
          {chapter.content.split("\n").map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>

        <div className="reader-navigation">
          <button
            className="prev-button"
            onClick={() => goToChapter(chapter.chapter_number - 1)}
            disabled={chapter.chapter_number <= 1}
          >
            Previous
          </button>
          <button
            className="next-button"
            onClick={() => goToChapter(chapter.chapter_number + 1)}
            disabled={chapter.chapter_number >= novel.total_chapters}
          >
            Next
          </button>
        </div>
        <section className="reader-annotations" aria-label="Bookmarks and notes">
          <header>
            <strong>Bookmarks & notes</strong>
            <span>{annotations.length}</span>
          </header>
          {annotations.filter((annotation) => annotation.chapter_number === chapter.chapter_number).slice(0, 8).map((annotation) => (
            <div className="reader-annotation" key={annotation.id}>
              <button type="button" onClick={() => { if (contentRef.current) contentRef.current.scrollTop = (annotation.percent / 100) * contentRef.current.scrollHeight; }}>
                {annotation.annotation_type === "bookmark" ? "🔖" : "📝"} {annotation.note || annotation.quote || `At ${Math.round(annotation.percent)}%`}
              </button>
              <button type="button" onClick={() => void removeAnnotation(annotation.id)} aria-label="Delete annotation">×</button>
            </div>
          ))}
        </section>
      </article>
    </div>
  );
};

export default Reader;
