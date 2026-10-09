import { Link } from "react-router-dom";
import { MoreHorizontal, Plus } from "lucide-react";
import { Badge, Button, Card, Cover, IconButton, Menu, Skeleton, SkeletonGroup, type MenuItem } from "../ui";
import type { DiscoveredNovel } from "../../types/discovery";
import { siteLabel, isExperimentalSite } from "../story/storyModel";
import { metaLine } from "./discoverOptions";

interface CardProps {
  novel: DiscoveredNovel;
  onAdd: (novel: DiscoveredNovel) => void;
  onHideAuthor: (novel: DiscoveredNovel) => void;
}

function DiscoverCard({ novel, onAdd, onHideAuthor }: CardProps) {
  const items: MenuItem[] = [
    ...(novel.source_url ? [{ label: `Open on ${siteLabel(novel.novel_site) ?? "site"}`, onSelect: () => window.open(novel.source_url, "_blank", "noopener,noreferrer") }] : []),
    ...(novel.author ? [{ label: `Hide author “${novel.author}”`, onSelect: () => onHideAuthor(novel) }] : []),
  ];
  return (
    <Card as="article" padding="none" className="discover-card" media={<Cover src={novel.img_url} title={novel.title} author={novel.author} size="fill" />}>
      <div className="discover-card__body">
        <h3 className="discover-card__title">
          <Link to={`/story/${novel.id}`} className="ui-stretched-link">{novel.title}</Link>
        </h3>
        {novel.author && <p className="discover-card__author">{novel.author}</p>}
        <p className="discover-card__meta">
          {metaLine(novel)}
          {isExperimentalSite(novel.novel_site) && <> <Badge tone="warning">Experimental</Badge></>}
        </p>
        <div className="discover-card__actions">
          <Button size="sm" variant="secondary" icon={<Plus aria-hidden="true" />} onClick={() => onAdd(novel)} aria-label={`Add ${novel.title} to library`}>
            Add
          </Button>
          {items.length > 0 && (
            <Menu align="end" items={items} trigger={(props) => <IconButton {...props} size="sm" label={`More actions for ${novel.title}`} icon={<MoreHorizontal aria-hidden="true" />} />} />
          )}
        </div>
      </div>
    </Card>
  );
}

interface ResultsGridProps {
  novels: DiscoveredNovel[];
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  countText: string | null;
  onRetry: () => void;
  onLoadMore: () => void;
  onAdd: (novel: DiscoveredNovel) => void;
  onHideAuthor: (novel: DiscoveredNovel) => void;
  /** Shown when there are no results (and no error). */
  empty: React.ReactNode;
}

/** H2 "Results", the count line, the card grid (H3 titles) and Load more. */
export function ResultsGrid({ novels, loading, loadingMore, hasMore, error, countText, onRetry, onLoadMore, onAdd, onHideAuthor, empty }: ResultsGridProps) {
  return (
    <section className="discover-results" aria-labelledby="discover-results-heading">
      <div className="discover-results__head">
        <h2 id="discover-results-heading">Results</h2>
        {countText && <p className="discover-results__count" role="status">{countText}</p>}
      </div>
      {error && (
        <div className="discover-results__error" role="alert">
          <p>{error}</p>
          <Button size="sm" onClick={onRetry}>Try again</Button>
        </div>
      )}
      {loading ? (
        <SkeletonGroup label="Loading stories" className="discover-grid">
          {Array.from({ length: 10 }).map((_, index) => (
            <div key={index} className="discover-card discover-card--skeleton">
              <Skeleton type="cover" />
              <Skeleton type="line" />
              <Skeleton type="line" />
            </div>
          ))}
        </SkeletonGroup>
      ) : novels.length === 0 ? (
        !error && empty
      ) : (
        <>
          <div className="discover-grid">
            {novels.map((novel) => (
              <DiscoverCard key={novel.id} novel={novel} onAdd={onAdd} onHideAuthor={onHideAuthor} />
            ))}
          </div>
          {hasMore && (
            <div className="discover-results__more">
              <Button onClick={onLoadMore} loading={loadingMore} disabled={loadingMore}>Load more</Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default ResultsGrid;
