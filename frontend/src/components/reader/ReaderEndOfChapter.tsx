import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

interface ReaderEndOfChapterProps {
  chapterNumber: number;
  next: { chapter_number: number; title: string; label: string } | null;
  /** First unread chapter, shown when it isn't simply the next one. */
  nextUnread: number | null;
  chapterHref: (chapterNumber: number) => string;
  storyHref: string;
}

/** End-of-chapter card: next chapter (primary), next unread, back to the story. */
const ReaderEndOfChapter: React.FC<ReaderEndOfChapterProps> = ({ chapterNumber, next, nextUnread, chapterHref, storyHref }) => (
  <nav className="reader-end" aria-label="End of chapter">
    <p className="reader-end__meta">End of chapter {chapterNumber}</p>
    {next ? (
      <Link className="ui-button ui-button--primary ui-button--lg reader-end__next" to={chapterHref(next.chapter_number)}>
        <span className="ui-button__label">
          Next: {next.label}{next.title && next.title !== next.label ? ` · ${next.title}` : ""}
        </span>
        <ArrowRight aria-hidden="true" />
      </Link>
    ) : (
      <p className="reader-end__last">You’re up to date with this story.</p>
    )}
    {nextUnread !== null && (
      <Link className="ui-button ui-button--secondary" to={chapterHref(nextUnread)}>
        <span className="ui-button__label">Continue from first unread · Chapter {nextUnread}</span>
      </Link>
    )}
    <Link className="ui-button ui-button--ghost" to={storyHref}>
      <span className="ui-button__label">Back to story</span>
    </Link>
  </nav>
);

export default ReaderEndOfChapter;
