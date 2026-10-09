import React, { useEffect, useMemo, useState } from "react";
import NovelList, { LibrarySortBy } from "../components/novel/NovelList";
import { ShelfManager } from "../components/organization/ShelfManager";
import { LibraryTitleMenu } from "../components/library/LibraryTitleMenu";
import { STORY_ADDED } from "../components/add/addStoryEvents";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { FOLLOW_STATE_LABELS } from "../components/library/followStates";
import { useLibraryContext } from "../context/useLibraryContext";
import { organizationService } from "../services/organizationService";
import { usePageTitle } from "../hooks/usePageTitle";
import { SlidersHorizontal } from "lucide-react";
import { Button, FilterChip, Input, Menu, PageHeader, SegmentedControl, Select } from "../components/ui";
import type { Novel } from "../types/novel";
import type { Shelf } from "../types/organization";
import "../styles/library-page.css";
import "../styles/organization.css";

interface LibraryPageProps {
  library_id: number;
}

const sourceOptions = [
  { value: "all", label: "All sources" },
  { value: "royalroad", label: "Royal Road" },
  { value: "spacebattles", label: "SpaceBattles" },
  { value: "fanfiction", label: "FanFiction.Net" },
  { value: "ao3", label: "Archive of Our Own" },
  { value: "sufficientvelocity", label: "Sufficient Velocity" },
  { value: "questionablequesting", label: "Questionable Questing" },
  { value: "scribblehub", label: "Scribble Hub (experimental)" },
];

const sortOptions = [
  { value: "recent", label: "Recently updated" },
  { value: "updated_since_read", label: "Updated since I last read" },
  { value: "personal_rating", label: "My rating" },
  { value: "title", label: "Title" },
  { value: "chapters", label: "Most chapters" },
];

const STATE_KEYS = ["reading", "plan_to_read", "on_hold", "completed", "dropped"] as const;

const LibraryPage: React.FC<LibraryPageProps> = ({ library_id }) => {
  const { libraries, activeLibraryId, selectLibrary } = useLibraryContext();
  const libraryMeta = useMemo(
    () => libraries.find((library) => library.id === library_id),
    [libraries, library_id]
  );
  const libraryName = libraryMeta?.name || "Library";
  // The heading shows the library name with its switcher; the top bar and tab title say "Library".
  usePageTitle("Library");

  const [searchTerm, setSearchTerm] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sortBy, setSortBy] = useState<LibrarySortBy>("recent");
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [shelfId, setShelfId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loadedNovels, setLoadedNovels] = useState<Novel[]>([]);
  const [userTag, setUserTag] = useState("");
  const [minRating, setMinRating] = useState(0);
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [shelvesOpen, setShelvesOpen] = useState(false);
  const [moreFilters, setMoreFilters] = useState(false);
  const wide = useMediaQuery("(min-width: 768px)");
  const [selectionMode, setSelectionMode] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (activeLibraryId !== library_id) {
      selectLibrary(library_id);
    }
  }, [activeLibraryId, library_id, selectLibrary]);

  useEffect(() => {
    let active = true;
    organizationService.listShelves().then((rows) => active && setShelves(rows)).catch(() => active && setShelves([]));
    organizationService.tagSuggestions("").then((tags) => active && setTagOptions(tags)).catch(() => active && setTagOptions([]));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ libraryId?: number }>).detail;
      if (!detail || detail.libraryId === library_id) setRefreshKey((prev) => prev + 1);
    };
    window.addEventListener(STORY_ADDED, listener);
    return () => window.removeEventListener(STORY_ADDED, listener);
  }, [library_id]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const novel of loadedNovels) counts[novel.follow_state] = (counts[novel.follow_state] ?? 0) + 1;
    return counts;
  }, [loadedNovels]);

  const extraFilters = (userTag ? 1 : 0) + (minRating > 0 ? 1 : 0);
  const showExtra = wide || moreFilters;
  const storyCount = loadedNovels.length;

  return (
    <div className="library-page">
      <PageHeader
        className="library-page__header"
        title={<LibraryTitleMenu libraryId={library_id} name={libraryName} />}
        description={storyCount > 0 ? `${storyCount} ${storyCount === 1 ? "story" : "stories"}` : undefined}
        actions={
          selectionMode ? (
            <Button variant="primary" onClick={() => setSelectionMode(false)}>Done</Button>
          ) : (
            <Menu
              align="end"
              items={[
                { label: "Select stories", onSelect: () => setSelectionMode(true) },
                { label: "Shelves…", onSelect: () => setShelvesOpen(true) },
              ]}
              trigger={(props) => <Button {...props} variant="secondary">Organize</Button>}
            />
          )
        }
      />

      <div className="library-toolbar" role="search" aria-label="Filter stories">
        <Input
          type="search"
          label="Search"
          hideLabel
          placeholder="Search by title or author"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          onClear={() => setSearchTerm("")}
          search
          fieldClassName="library-toolbar__search"
        />
        <Select
          label="Site"
          hideLabel
          value={sourceFilter}
          onChange={(event) => setSourceFilter(event.target.value)}
          options={sourceOptions}
        />
        {shelves.length > 0 && (
          <Select
            label="Shelf"
            hideLabel
            value={shelfId == null ? "" : String(shelfId)}
            onChange={(event) => setShelfId(event.target.value ? Number(event.target.value) : null)}
            options={[{ value: "", label: "All shelves" }, ...shelves.map((shelf) => ({ value: String(shelf.id), label: shelf.name }))]}
          />
        )}
        <Select
          label="Sort"
          hideLabel
          value={sortBy}
          onChange={(event) => setSortBy(event.target.value as LibrarySortBy)}
          options={sortOptions}
        />
        {!wide && (
          <Button
            variant="secondary"
            icon={<SlidersHorizontal aria-hidden="true" />}
            aria-expanded={moreFilters}
            aria-controls="library-more-filters"
            onClick={() => setMoreFilters((prev) => !prev)}
            className="library-toolbar__more"
          >
            Filters{extraFilters > 0 ? ` (${extraFilters})` : ""}
          </Button>
        )}
        <div id="library-more-filters" className="library-toolbar__extra" hidden={!showExtra}>
          <Input
            label="My tag"
            hideLabel={wide}
            list="library-user-tags"
            value={userTag}
            placeholder="My tag"
            onChange={(event) => setUserTag(event.target.value)}
          />
          <datalist id="library-user-tags">
            {tagOptions.map((tag) => <option key={tag} value={tag} />)}
          </datalist>
          <Select
            label="My rating"
            hideLabel={wide}
            value={String(minRating)}
            onChange={(event) => setMinRating(Number(event.target.value))}
            options={[
              { value: "0", label: "Any rating" },
              ...[1, 2, 3, 4, 5].map((stars) => ({ value: String(stars), label: `${stars}★ and up` })),
            ]}
          />
        </div>
        <SegmentedControl
          label="View"
          value={viewMode}
          onChange={setViewMode}
          options={[
            { value: "grid", label: "Grid" },
            { value: "list", label: "List" },
          ]}
        />
      </div>

      <div className="library-status-chips" role="group" aria-label="Filter by reading status">
        <FilterChip selected={statusFilter === "all"} onChange={() => setStatusFilter("all")}>
          All ({loadedNovels.length})
        </FilterChip>
        {STATE_KEYS.filter((key) => statusCounts[key]).map((key) => (
          <FilterChip
            key={key}
            selected={statusFilter === key}
            onChange={() => setStatusFilter(statusFilter === key ? "all" : key)}
          >
            {FOLLOW_STATE_LABELS[key]} ({statusCounts[key]})
          </FilterChip>
        ))}
      </div>

      <h2 className="visually-hidden">Stories</h2>
      <NovelList
        library_id={library_id}
        searchTerm={searchTerm}
        sourceFilter={sourceFilter}
        sortBy={sortBy}
        viewMode={viewMode}
        selectionMode={selectionMode}
        refreshKey={refreshKey}
        shelves={shelves}
        onShelvesChanged={setShelves}
        shelfId={shelfId}
        userTag={userTag}
        minRating={minRating}
        statusFilter={statusFilter}
        onNovelsLoaded={setLoadedNovels}
      />

      <ShelfManager
        open={shelvesOpen}
        onClose={() => setShelvesOpen(false)}
        shelves={shelves}
        activeShelfId={shelfId}
        onSelect={setShelfId}
        onChanged={setShelves}
      />
    </div>
  );
};

export default LibraryPage;
