import React from "react";
import { Link } from "react-router-dom";
import { Badge, Banner, Card, Cover } from "../ui";
import { Novel } from "../../types/novel";
import { displayTitle } from "../../utils/displayTitle";
import type { Shelf } from "../../types/organization";
import { ShelfPicker } from "../organization/ShelfPicker";
import { FOLLOW_STATE_LABELS, storyHref } from "./followStates";

interface LibraryStoryCardProps {
  novel: Novel;
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
  const title = displayTitle(novel);
  const href = storyHref(novel, libraryId);
  const followLabel = FOLLOW_STATE_LABELS[novel.follow_state];
  const hasNext = novel.next_unread_chapter_number != null;
  const failed = novel.scrape_status === "failed";
  const pending = novel.scrape_status === "pending";

  const titleNode = selectionMode ? (
    <span className="library-card__title">{title}</span>
  ) : (
    <Link to={href} className="library-card__title ui-stretched-link">
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
          {novel.novel_site && <Badge>{novel.novel_site.toUpperCase()}</Badge>}
        </div>
        <h3 className="library-card__heading">{titleNode}</h3>
        <p className="library-card__author">{novel.author || "Unknown author"}</p>
        <p className="library-card__meta">
          {novel.chapter_count != null ? `${novel.chapter_count} chapters` : "Chapters unknown"}
          {novel.rating != null && ` · ${novel.rating.toFixed(1)} rating`}
        </p>
        {failed && (
          <Banner tone="warning" action={<Link to={href}>Open story</Link>}>
            We couldn't update this story. Details may be out of date.
          </Banner>
        )}
        {pending && <p className="library-card__pending">Update in progress</p>}
        {hasNext && !selectionMode && (
          <Link
            to={`/library/${libraryId}/novels/${novel.id}/${novel.next_unread_chapter_number}`}
            className="ui-button ui-button--secondary ui-button--sm library-card__continue"
          >
            Continue at chapter {novel.next_unread_chapter_number}
          </Link>
        )}
      </div>
    </Card>
  );
};

export default LibraryStoryCard;
