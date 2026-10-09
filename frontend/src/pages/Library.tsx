import React, { useEffect, useMemo, useState } from "react";
import NovelList, { LibrarySortBy } from "../components/novel/NovelList";
import CreateNovelForm from "../components/novel/CreateNovelForm";
import { ShelfBar } from "../components/organization/ShelfBar";
import { FOLLOW_STATE_LABELS } from "../components/library/followStates";
import { useLibraryContext } from "../context/useLibraryContext";
import { organizationService } from "../services/organizationService";
import { usePageTitle } from "../hooks/usePageTitle";
import { Button, FilterChip, Input, PageHeader, SegmentedControl, Select } from "../components/ui";
import type { Novel } from "../types/novel";
import type { Shelf } from "../types/organization";
import "../styles/library-page.css";
import "../styles/organization.css";

interface LibraryPageProps {
  library_id: number;
  /** Story link handed over from Home (`location.state.storyLink`); opens the add drawer prefilled. */
  prefillUrl?: string | null;
}

const sourceOptions = [
  { value: "all", label: "All sources" },
  { value: "royalroad", label: "RoyalRoad" },
  { value: "spacebattles", label: "SpaceBattles" },
  { value: "fanfiction", label: "FanFiction" },
  { value: "ao3", label: "AO3" },
  { value: "sufficientvelocity", label: "Sufficient Velocity" },
  { value: "questionablequesting", label: "Questionable Questing" },
  { value: "scribblehub", label: "ScribbleHub (experimental)" },
];

const sortOptions = [
  { value: "recent", label: "Recently updated" },
  { value: "updated_since_read", label: "Updated since I last read" },
  { value: "personal_rating", label: "My rating" },
  { value: "title", label: "Title" },
  { value: "chapters", label: "Chapter count" },
];

const STATE_KEYS = ["reading", "plan_to_read", "on_hold", "completed", "dropped"] as const;

const LibraryPage: React.FC<LibraryPageProps> = ({ library_id, prefillUrl = null }) => {
  const { libraries, activeLibraryId, selectLibrary } = useLibraryContext();
  const libraryMeta = useMemo(
    () => libraries.find((library) => library.id === library_id),
    [libraries, library_id]
  );
  const libraryName = libraryMeta?.name || "Library";
  usePageTitle(libraryName);

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
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [drawerUrl, setDrawerUrl] = useState("");
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
    if (!prefillUrl) return;
    setDrawerUrl(prefillUrl);
    setIsDrawerOpen(true);
  }, [prefillUrl]);

  useEffect(() => {
    const listener = (event: Event) => {
      const customEvent = event as CustomEvent<{ libraryId?: number }>;
      if (!customEvent.detail || customEvent.detail.libraryId === library_id) {
        setDrawerUrl("");
        setIsDrawerOpen(true);
      }
    };
    window.addEventListener("nexus:add-novel", listener);
    return () => window.removeEventListener("nexus:add-novel", listener);
  }, [library_id]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const novel of loadedNovels) counts[novel.follow_state] = (counts[novel.follow_state] ?? 0) + 1;
    return counts;
  }, [loadedNovels]);

  const handleDrawerSuccess = () => {
    setRefreshKey((prev) => prev + 1);
  };

  const openAdd = () => {
    setDrawerUrl("");
    setIsDrawerOpen(true);
  };

  return (
    <div className="library-page">
      <PageHeader
        title={libraryName}
        description="Your saved stories. Open one to read, or add a new story from a link."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => setSelectionMode((prev) => !prev)}
            >
              {selectionMode ? "Done" : "Organize"}
            </Button>
            <Button variant="primary" onClick={openAdd}>
              Add story
            </Button>
          </>
        }
      />

      <div className="library-toolbar">
        <Input
          type="search"
          label="Search"
          hideLabel
          placeholder="Search by title or author"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          onClear={() => setSearchTerm("")}
          search
        />
        <Select
          label="Source"
          hideLabel
          value={sourceFilter}
          onChange={(event) => setSourceFilter(event.target.value)}
          options={sourceOptions}
        />
        <Select
          label="Sort"
          hideLabel
          value={sortBy}
          onChange={(event) => setSortBy(event.target.value as LibrarySortBy)}
          options={sortOptions}
        />
        <Input
          label="My tag"
          hideLabel
          list="library-user-tags"
          value={userTag}
          placeholder="My tag"
          onChange={(event) => setUserTag(event.target.value)}
        />
        <datalist id="library-user-tags">
          {tagOptions.map((tag) => <option key={tag} value={tag} />)}
        </datalist>
        <Select
          label="Minimum my rating"
          hideLabel
          value={String(minRating)}
          onChange={(event) => setMinRating(Number(event.target.value))}
          options={[
            { value: "0", label: "Any rating" },
            ...[1, 2, 3, 4, 5].map((stars) => ({ value: String(stars), label: `${stars}★ and up` })),
          ]}
        />
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

      <ShelfBar
        shelves={shelves}
        activeShelfId={shelfId}
        onSelect={setShelfId}
        onChanged={setShelves}
      />

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

      <CreateNovelForm
        library_id={library_id}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onSuccess={handleDrawerSuccess}
        initialUrl={drawerUrl}
      />
    </div>
  );
};

export default LibraryPage;
