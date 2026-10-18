import React, { useEffect, useMemo, useState, useSyncExternalStore } from "react";
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
import SmartShelves from "../components/organization/SmartShelves";
import { libraryViewService, type LibraryViewOptions, type LibraryViewPage, type OwnedLibraryDefinition, type FollowState } from "../services/libraryViewService";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";
import type { Shelf } from "../types/organization";
import "../styles/library-page.css";
import "../styles/organization.css";

interface LibraryPageProps {
  library_id: number;
}

const sortOptions = [
  { value: "recent", label: "Recently updated" },
  { value: "updated_since_read", label: "Updated since I last read" },
  { value: "personal_rating", label: "My rating" },
  { value: "title", label: "Title" },
  { value: "chapters", label: "Most chapters" },
];

const STATE_KEYS = ["reading", "plan_to_read", "on_hold", "completed", "dropped", "ignored"] as const;

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
  const [page, setPage] = useState<LibraryViewPage | null>(null);
  const [options,setOptions] = useState<LibraryViewOptions|null>(null);
  const [smartOpen,setSmartOpen] = useState(false);
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
    libraryViewService.options().then(values => { if(active){ setOptions(values);setTagOptions(values.user_tags); } }).catch(() => { if(active)setTagOptions([]); });
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

  const statusCounts = page?.status_counts ?? {};
  const extraFilters = (userTag ? 1 : 0) + (minRating > 0 ? 1 : 0);
  const showExtra = wide || moreFilters;
  const storyCount = page?.library_total;
  const currentDefinition = useMemo<OwnedLibraryDefinition>(() => ({version:1,scope:"owned_library",library_ids:[library_id],q:searchTerm,source:sourceFilter==="all"?null:sourceFilter,follow_states:statusFilter==="all"?[]:[statusFilter as FollowState],user_tag:userTag.trim()||null,min_rating:minRating||null,shelf_id:shelfId,sort_by:sortBy}), [library_id,searchTerm,sourceFilter,statusFilter,userTag,minRating,shelfId,sortBy]);
  const sourceOptions = [{value:"all",label:"All sources"},...(options?.sources??[]).map(source=>({value:source.id,label:source.label})),...(sourceFilter!=="all"&&!options?.sources.some(source=>source.id===sourceFilter)?[{value:sourceFilter,label:sourceFilter}]:[])];

  return (
    <div className="library-page">
      <PageHeader
        className="library-page__header"
        title={<LibraryTitleMenu libraryId={library_id} name={libraryName} />}
        description={storyCount !== undefined ? `${storyCount} ${storyCount === 1 ? "story" : "stories"}` : undefined}
        actions={
          selectionMode ? (
            <Button variant="primary" onClick={() => setSelectionMode(false)}>Done</Button>
          ) : (
            <Menu
              align="end"
              items={[
                { label: "Select stories", onSelect: () => setSelectionMode(true) },
                { label: "Shelves…", onSelect: () => setShelvesOpen(true) },
                { label: "Smart shelves…", onSelect: () => setSmartOpen(true) },
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
          maxLength={500}
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
          All ({page ? Object.values(statusCounts).reduce((sum,value)=>sum+(value??0),0) : "…"})
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
        onPageLoaded={setPage}
      />

      <SmartShelves open={smartOpen} onClose={()=>setSmartOpen(false)} libraryId={library_id} initialDefinition={currentDefinition} shelves={shelves}/>

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

export default function AccountLibraryPage(props:LibraryPageProps){ const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration); return <LibraryPage key={`${generation}:${props.library_id}`} {...props}/>; }
