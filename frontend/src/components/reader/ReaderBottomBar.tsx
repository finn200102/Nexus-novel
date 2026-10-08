import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button, Progress } from "../ui";

interface ReaderBottomBarProps {
  chapterNumber: number;
  totalChapters: number;
  /** Chapter progress 0–100 (scroll position or page). */
  percent: number;
  minutesLeft: number | null;
  paged: boolean;
  page: number;
  pageCount: number;
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  /** Paged mode: previous/next page buttons for keyboard and switch users. */
  onPreviousPage: () => void;
  onNextPage: () => void;
}

const minutesLabel = (minutes: number | null) =>
  minutes === null ? null : minutes <= 1 ? "1 min left" : `${minutes} min left`;

/** Reader bottom bar: chapter progress, position text and previous/next. */
const ReaderBottomBar: React.FC<ReaderBottomBarProps> = ({
  chapterNumber, totalChapters, percent, minutesLeft, paged, page, pageCount,
  hasPrevious, hasNext, onPrevious, onNext, onPreviousPage, onNextPage,
}) => {
  const chapterText = `Ch. ${chapterNumber} of ${Math.max(totalChapters, chapterNumber)}`;
  const pageText = `Page ${page + 1} of ${pageCount}`;
  const status = paged ? `${pageText} · ${chapterText}` : [chapterText, minutesLabel(minutesLeft)].filter(Boolean).join(" · ");
  return (
    <div className="reader-bottombar">
      <Progress
        className="reader-bottombar__progress"
        label={paged ? "Page progress" : "Chapter progress"}
        value={paged ? page + 1 : Math.round(percent)}
        max={paged ? pageCount : 100}
        valueText={paged ? pageText : `${Math.round(percent)}% of chapter ${chapterNumber}`}
      />
      <div className="reader-bottombar__row">
        {paged ? (
          <Button variant="ghost" size="sm" icon={<ChevronLeft aria-hidden="true" />} onClick={page > 0 ? onPreviousPage : onPrevious} disabled={page === 0 && !hasPrevious}>
            <span className="reader-bottombar__label">{page > 0 ? "Previous page" : "Previous chapter"}</span>
          </Button>
        ) : (
          <Button variant="ghost" size="sm" icon={<ChevronLeft aria-hidden="true" />} onClick={onPrevious} disabled={!hasPrevious}>
            <span className="reader-bottombar__label">Previous</span>
          </Button>
        )}
        <span className="reader-bottombar__status">{status}</span>
        {paged ? (
          <Button variant="ghost" size="sm" iconEnd={<ChevronRight aria-hidden="true" />} onClick={page < pageCount - 1 ? onNextPage : onNext} disabled={page >= pageCount - 1 && !hasNext}>
            <span className="reader-bottombar__label">{page < pageCount - 1 ? "Next page" : "Next chapter"}</span>
          </Button>
        ) : (
          <Button variant="ghost" size="sm" iconEnd={<ChevronRight aria-hidden="true" />} onClick={onNext} disabled={!hasNext}>
            <span className="reader-bottombar__label">Next</span>
          </Button>
        )}
      </div>
    </div>
  );
};

export default ReaderBottomBar;
