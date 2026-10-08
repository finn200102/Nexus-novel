import React, { useEffect, useMemo, useState } from "react";
import NovelList from "../components/novel/NovelList";
import CreateNovelForm from "../components/novel/CreateNovelForm";
import { useLibraryContext } from "../context/useLibraryContext";
import "../styles/library.css";

interface LibraryPageProps {
  library_id: number;
}

const sourceOptions = [
  { value: "all", label: "All sources" },
  { value: "royalroad", label: "RoyalRoad" },
  { value: "spacebattles", label: "SpaceBattles" },
  { value: "fanfiction", label: "FanFiction" },
  { value: "ao3", label: "AO3" },
  { value: "sufficientvelocity", label: "Sufficient Velocity" },
  { value: "questionablequesting", label: "Questionable Questing" },
  { value: "scribblehub", label: "ScribbleHub" },
];

const LibraryPage: React.FC<LibraryPageProps> = ({ library_id }) => {
  const { libraries, activeLibraryId, selectLibrary } = useLibraryContext();
  const [searchTerm, setSearchTerm] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"recent" | "title" | "chapters">("recent");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (activeLibraryId !== library_id) {
      selectLibrary(library_id);
    }
  }, [activeLibraryId, library_id, selectLibrary]);

  useEffect(() => {
    const listener = (event: Event) => {
      const customEvent = event as CustomEvent<{ libraryId?: number }>;
      if (!customEvent.detail || customEvent.detail.libraryId === library_id) {
        setIsDrawerOpen(true);
      }
    };
    window.addEventListener("nexus:add-novel", listener);
    return () => window.removeEventListener("nexus:add-novel", listener);
  }, [library_id]);

  const libraryMeta = useMemo(
    () => libraries.find((library) => library.id === library_id),
    [libraries, library_id]
  );

  const handleDrawerSuccess = () => {
    setRefreshKey((prev) => prev + 1);
  };

  return (
    <div className="library-workspace">
      <header className="library-workspace__header">
        <div>
          <p className="library-workspace__eyebrow">Library</p>
          <h1>{libraryMeta?.name || "Library"}</h1>
          <p className="library-workspace__summary">
            Focus on your curated collection, keep metadata up to date, and manage downloads.
          </p>
        </div>
        <div className="library-workspace__actions">
          <button
            type="button"
            className="library-ghost-btn"
            onClick={() => setSelectionMode((prev) => !prev)}
          >
            {selectionMode ? "Done" : "Organize"}
          </button>
          <button
            type="button"
            className="library-primary-btn"
            onClick={() => setIsDrawerOpen(true)}
          >
            Add novel
          </button>
        </div>
      </header>

      <div className="library-controls">
        <div className="library-search">
          <input
            type="search"
            placeholder="Search by title or author"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
          />
        </div>
        <div className="library-select-group">
          <label>
            Source
            <select
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
            >
              {sourceOptions.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sort
            <select
              value={sortBy}
              onChange={(event) =>
                setSortBy(event.target.value as "recent" | "title" | "chapters")
              }
            >
              <option value="recent">Recently updated</option>
              <option value="title">Title</option>
              <option value="chapters">Chapter count</option>
            </select>
          </label>
        </div>
        <div className="library-view-toggle">
          <button
            type="button"
            className={viewMode === "grid" ? "is-active" : ""}
            onClick={() => setViewMode("grid")}
          >
            Grid
          </button>
          <button
            type="button"
            className={viewMode === "list" ? "is-active" : ""}
            onClick={() => setViewMode("list")}
          >
            List
          </button>
        </div>
      </div>

      <NovelList
        library_id={library_id}
        searchTerm={searchTerm}
        sourceFilter={sourceFilter}
        sortBy={sortBy}
        viewMode={viewMode}
        selectionMode={selectionMode}
        refreshKey={refreshKey}
      />

      <CreateNovelForm
        library_id={library_id}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onSuccess={handleDrawerSuccess}
      />
    </div>
  );
};

export default LibraryPage;
