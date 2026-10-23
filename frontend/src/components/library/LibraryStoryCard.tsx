import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Badge, Card, Cover } from "../ui";
import { Novel } from "../../types/novel";
import { displayTitle } from "../../utils/displayTitle";
import type { Shelf } from "../../types/organization";
import { ShelfPicker } from "../organization/ShelfPicker";
import { FOLLOW_STATE_LABELS, storyHref } from "./followStates";
import { siteLabel } from "../story/storyModel";

interface LibraryStoryCardProps {
  novel: Pick<Novel,"id"|"title"|"library_id"> & Partial<Omit<Novel,"id"|"title"|"library_id"|"url">> & {url?:string|null};
  libraryId: number;
  personalRating?: number | null;
  selectionMode: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  shelves: Shelf[];
  onShelvesChanged?: (shelves: Shelf[]) => void;
  /** Viewing list layout: the card is a row instead of a tile. */
  compact?: boolean;
}

const LibraryStoryCard: React.FC<LibraryStoryCardProps> = ({
  novel,
  libraryId,
  personalRating,
  selectionMode,
  selected,
  onToggleSelect,
  shelves,
  onShelvesChanged,
  compact = false,
}) => {
  const location=useLocation();
  const libraryReturn=location.pathname==="/library"?`${location.pathname}${location.search}`:`/library?library=${libraryId}`;
  const title = displayTitle(novel);
  const href = storyHref(novel, libraryId);
  const followLabel = novel.follow_state ? FOLLOW_STATE_LABELS[novel.follow_state] : null;
  const hasNext = novel.next_unread_chapter_number != null;
  const failed = novel.scrape_status === "failed";
  const pending = novel.scrape_status === "pending";

  const titleNode = selectionMode ? (
    <span className="library-card__title">{title}</span>
  ) : (
    <Link to={href} state={{libraryReturn}} className="library-card__title ui-stretched-link">
      {title}
    </Link>
  );

  return (
    <Card
      as="article"
      padding="none"
      className={`library-card${compact ? " library-card--compact" : ""}${selected ? " is-selected" : ""}`}
      media={
        <div className="library-card__cover">
          <Cover src={novel.img_url || novel.cover_image} title={title} size={compact ? 72 : "fill"} />
          {selectionMode && (
            <input
              type="checkbox"
              className="library-card__select"
              checked={selected}
              onChange={onToggleSelect}
              aria-label={`Select ${title}`}
            />
          )}
        </div>
      }
      footer={
        !selectionMode && (personalRating != null || shelves.length > 0) ? (
          <div className="library-card__organize">
            {personalRating != null && (
              <span className="library-card__rating" aria-label={`Your rating ${personalRating} of 5`}>
                ★ {personalRating}
              </span>
            )}
            {shelves.length > 0 && (
              <ShelfPicker novelId={novel.id} shelves={shelves} onChanged={onShelvesChanged} />
            )}
          </div>
        ) : undefined
      }
    >
      <div className="library-card__body">
        <div className="library-card__badges">
          {followLabel && <Badge tone={novel.follow_state === "reading" ? "accent" : "neutral"}>{followLabel}</Badge>}
          {novel.novel_site && <Badge>{siteLabel(novel.novel_site)}</Badge>}
          {failed && <Badge tone="warning">Couldn't update</Badge>}
        </div>
        <h3 className="library-card__heading">{titleNode}</h3>
        <p className="library-card__author">{novel.author || "Unknown author"}</p>
        {hasNext && !selectionMode ? (
          <Link
            to={`/library/${libraryId}/novels/${novel.id}/${novel.next_unread_chapter_number}`}
            className="library-card__next"
            aria-label={`Continue ${title} at chapter ${novel.next_unread_chapter_number}`}
          >
            Next: Chapter {novel.next_unread_chapter_number}
            {novel.chapter_count != null && <span className="library-card__of"> · {novel.chapter_count} chapters</span>}
          </Link>
        ) : (
          <p className="library-card__meta">
            {novel.follow_state === "completed"
              ? "Finished"
              : novel.chapter_count != null
                ? `${novel.chapter_count} chapters`
                : "Chapters not loaded yet"}
          </p>
        )}
        {pending && <p className="library-card__pending">Update in progress</p>}
      </div>
    </Card>
  );
};

export default LibraryStoryCard;
