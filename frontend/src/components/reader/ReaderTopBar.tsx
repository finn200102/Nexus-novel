import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Bookmark, BookmarkCheck, Headphones, List, MoreHorizontal } from "lucide-react";
import { IconButton, Menu, type MenuItem } from "../ui";

interface ReaderTopBarProps {
  storyTitle: string;
  chapterTitle: string;
  chapterLine: string;
  backTo: string;
  /** Phones show Chapters, Aa and More; Listen and Bookmark move into More. */
  compact: boolean;
  bookmarked: boolean;
  listening: boolean;
  onChapters: () => void;
  onBookmark: () => void;
  onListen: () => void;
  /** Text settings trigger (popover on desktop, sheet button on phones). */
  settings: React.ReactNode;
  moreItems: MenuItem[];
  chaptersRef?: React.Ref<HTMLButtonElement>;
}

/** Reader top bar: back to the story, story and chapter title, then the reader actions. */
const ReaderTopBar: React.FC<ReaderTopBarProps> = ({
  storyTitle, chapterTitle, chapterLine, backTo, compact, bookmarked, listening,
  onChapters, onBookmark, onListen, settings, moreItems, chaptersRef,
}) => {
  const items: MenuItem[] = compact
    ? [
        { label: listening ? "Close player" : "Listen", icon: <Headphones aria-hidden="true" />, onSelect: onListen },
        { label: bookmarked ? "Remove bookmark" : "Bookmark this place", icon: <Bookmark aria-hidden="true" />, onSelect: onBookmark, hint: "B" },
        { type: "separator" },
        ...moreItems,
      ]
    : moreItems;
  return (
    <div className="reader-topbar">
      <Link className="ui-icon-button ui-icon-button--tip-below reader-topbar__back" to={backTo} aria-label={`Back to ${storyTitle}`}>
        <ArrowLeft aria-hidden="true" />
        <span className="ui-tooltip" aria-hidden="true">Back to story</span>
      </Link>
      <div className="reader-topbar__titles">
        <span className="reader-topbar__story">{chapterTitle}</span>
        <span className="reader-topbar__chapter">{chapterLine}</span>
      </div>
      <div className="reader-topbar__actions">
        <IconButton ref={chaptersRef} label="Chapters" icon={<List />} tooltip="below" onClick={onChapters} />
        {settings}
        {!compact && (
          <>
            <IconButton label="Listen" icon={<Headphones />} tooltip="below" pressed={listening} onClick={onListen} />
            <IconButton label="Bookmark" icon={bookmarked ? <BookmarkCheck /> : <Bookmark />} tooltip="below" pressed={bookmarked} onClick={onBookmark} />
          </>
        )}
        <Menu
          align="end"
          items={items}
          trigger={(props) => <IconButton {...props} label="More reader actions" icon={<MoreHorizontal />} tooltip="below" />}
        />
      </div>
    </div>
  );
};

export default ReaderTopBar;
