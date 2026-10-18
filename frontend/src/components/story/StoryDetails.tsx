import React, { useState } from "react";
import StorySourceMigration from "./StorySourceMigration";
import StoryEditions from "./StoryEditions";
import type { LibraryEntry } from "../../services/storyService";
import type { Novel } from "../../types/novel";
import { Button } from "../ui";
import { compactNumber, formatDate, isExperimentalSite, relativeTime, siteLabel, statusLabel, type StoryView } from "./storyModel";

interface StoryDetailsProps {
  view: StoryView;
  novel: Novel | null;
  entries: LibraryEntry[];
  updating: boolean;
  onRefresh: () => void;
  onRescrape: () => void;
  onCheckStatus: () => void;
}

const SCRAPE_TEXT: Record<string, string> = {
  pending: "Getting chapters from the source…",
  failed: "The last update from the source failed.",
  completed: "Up to date",
};

/** Details tab: sources and editions in plain words, facts, IDs for support, update controls. */
const StoryDetails: React.FC<StoryDetailsProps> = ({ view, novel, entries, updating, onRefresh, onRescrape, onCheckStatus }) => {
  const [migrationOpen, setMigrationOpen] = useState(false);
  const site = siteLabel(view.site);
  const rows: Array<[string, React.ReactNode]> = [];
  const add = (label: string, value: React.ReactNode | null | undefined) => {
    if (value !== null && value !== undefined && value !== "") rows.push([label, value]);
  };
  const count = (value: number | null) => (value ? compactNumber(value) : null);

  add("Source", site && (
    <>
      {view.sourceUrl ? <a href={view.sourceUrl} target="_blank" rel="noopener noreferrer">{site}</a> : site}
      {isExperimentalSite(view.site) && " (experimental support)"}
    </>
  ));
  add("Author", view.author);
  add("Status", statusLabel(view));
  add("First published", formatDate(view.published));
  add("Last updated", formatDate(view.updated));
  add("Chapters", view.chapterCount ? view.chapterCount.toLocaleString("en-US") : null);
  add("Words", view.wordCount ? view.wordCount.toLocaleString("en-US") : null);
  add("Views", count(view.views));
  add("Favorites", count(view.favorites));
  add("Follows", count(view.follows));
  add("Reviews", count(view.reviews));
  add("Rating on source", view.rating ? String(view.rating) : null);
  if (entries.length > 0) add("In your libraries", entries.map((entry) => entry.library_name).join(", "));
  if (novel) {
    add("Story info", (
      <>
        {SCRAPE_TEXT[novel.scrape_status ?? "completed"] ?? novel.scrape_status}
        {novel.scrape_status === "failed" && novel.scrape_error ? ` (${novel.scrape_error})` : ""}
      </>
    ));
    add("Last checked", relativeTime(novel.parsed_at ?? novel.updated_at));
  }
  add("Catalog ID", view.metadataId ? String(view.metadataId) : null);
  add("Site story ID", view.siteStoryId ? String(view.siteStoryId) : null);
  add("Library story ID", novel ? String(novel.id) : null);

  return (
    <div className="story-body story-body--single">
      <div className="story-main">
        <dl className="story-facts-list">
          {rows.map(([label, value]) => (
            <div key={label} className="story-facts-list__row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {novel && (
          <div className="story-row">
            <Button size="sm" variant="secondary" loading={updating} onClick={onRefresh}>Update story info</Button>
            <Button size="sm" variant="ghost" disabled={updating} onClick={onRescrape}>Download story info again</Button>
            {(novel.scrape_status === "pending" || novel.scrape_status === "failed") && (
              <Button size="sm" variant="ghost" disabled={updating} onClick={onCheckStatus}>Check update status</Button>
            )}
          </div>
        )}
        {view.metadataId != null && <StoryEditions metadataId={view.metadataId} />}
        {novel && <details className="story-source-migration-disclosure" onToggle={event => { if (event.target === event.currentTarget) setMigrationOpen(event.currentTarget.open); }}><summary>Continue with another source</summary>{migrationOpen && <StorySourceMigration novelId={novel.id} libraryId={novel.library_id} />}</details>}
      </div>
    </div>
  );
};

export default StoryDetails;
