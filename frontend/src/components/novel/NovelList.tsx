import React, { useEffect, useMemo, useState } from "react";
import { novelService } from "../../services/novelService";
import LibraryStoryCard from "../library/LibraryStoryCard";
import { EmptyState } from "../ui";
import { Novel } from "../../types/novel";
import { NovelCardSkeleton } from "../common/Skeleton";
import { organizationService } from "../../services/organizationService";
import type { LibraryPersonalEntry, Shelf } from "../../types/organization";
import type { LibraryNovelOptions } from "../../services/novelService";

export type LibrarySortBy = "recent" | "title" | "chapters" | "updated_since_read" | "personal_rating";

interface NovelListProps {
  library_id: number;
  searchTerm: string;
  sourceFilter: string;
  sortBy: LibrarySortBy;
  viewMode: "grid" | "list";
  selectionMode: boolean;
  refreshKey?: number;
  shelves?: Shelf[];
  onShelvesChanged?: (shelves: Shelf[]) => void;
  shelfId?: number | null;
  userTag?: string;
  minRating?: number;
  /** Follow state to show ("all" for every story). Filtered on the client. */
  statusFilter?: string;
  /** Receives every story the current query returned, before the status filter (for chip counts). */
  onNovelsLoaded?: (novels: Novel[]) => void;
}

// The server orders these, so the client keeps the order it receives.
const SERVER_SORTS: LibrarySortBy[] = ["updated_since_read", "personal_rating"];

const NovelList: React.FC<NovelListProps> = ({
  library_id,
  searchTerm,
  sourceFilter,
  sortBy,
  viewMode,
  selectionMode,
  refreshKey = 0,
  shelves = [],
  onShelvesChanged,
  shelfId = null,
  userTag = "",
  minRating = 0,
  statusFilter = "all",
  onNovelsLoaded,
}) => {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [personal, setPersonal] = useState<Record<string, LibraryPersonalEntry>>({});
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNovels, setSelectedNovels] = useState<Set<number>>(new Set());
  const [deleteLoading, setDeleteLoading] = useState<boolean>(false);

  useEffect(() => {
    let isCancelled = false;
    const fetchNovels = async () => {
      try {
        setLoading(true);
        const options: LibraryNovelOptions = {
          shelfId,
          userTag: userTag.trim(),
          minRating,
          sortBy: SERVER_SORTS.includes(sortBy) ? sortBy : undefined,
        };
        const data = await novelService.getAllNovels(library_id, searchTerm, options);
        if (isCancelled) return;
        if (Array.isArray(data)) {
          setNovels(data);
          setError(null);
        } else {
          setError("We couldn't load your stories. Reload the page to try again.");
        }
      } catch (err) {
        if (!isCancelled) {
          console.error("Failed to fetch novels:", err);
          setError("We couldn't load your stories. Check your connection and reload the page.");
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    };
    fetchNovels();
    return () => {
      isCancelled = true;
    };
  }, [library_id, searchTerm, refreshKey, shelfId, userTag, minRating, sortBy]);

  useEffect(() => {
    let active = true;
    organizationService
      .libraryPersonal(library_id)
      .then((entries) => active && setPersonal(entries))
      .catch(() => active && setPersonal({}));
    return () => {
      active = false;
    };
  }, [library_id, refreshKey]);

  useEffect(() => {
    onNovelsLoaded?.(novels);
  }, [novels, onNovelsLoaded]);

  useEffect(() => {
    if (!selectionMode) {
      setSelectedNovels(new Set());
    }
  }, [selectionMode]);

  const processedNovels = useMemo(() => {
    const normalizedSource = sourceFilter.toLowerCase();
    const filtered = novels.filter((novel) => {
      if (statusFilter !== "all" && novel.follow_state !== statusFilter) return false;
      if (normalizedSource === "all") return true;
      const site = (novel.novel_site || novel.source_url || "").toLowerCase();
      return site.includes(normalizedSource);
    });

    if (SERVER_SORTS.includes(sortBy)) return filtered;

    const sorted = [...filtered];
    if (sortBy === "recent") {
      sorted.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    } else if (sortBy === "title") {
      sorted.sort((a, b) => a.title.localeCompare(b.title));
    } else {
      sorted.sort(
        (a, b) => (b.chapter_count || 0) - (a.chapter_count || 0)
      );
    }
    return sorted;
  }, [novels, sourceFilter, sortBy, statusFilter]);

  const handleNovelClick = (novelId: number) => {
    if (selectionMode) {
      const updatedSelection = new Set(selectedNovels);
      if (selectedNovels.has(novelId)) {
        updatedSelection.delete(novelId);
      } else {
        updatedSelection.add(novelId);
      }
      setSelectedNovels(updatedSelection);
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedNovels.size === 0) return;
    if (
      !window.confirm(
        `Delete ${selectedNovels.size} selected ${
          selectedNovels.size === 1 ? "novel" : "novels"
        }?`
      )
    ) {
      return;
    }
    setDeleteLoading(true);
    try {
      const novelIdsArray = Array.from(selectedNovels);
      await novelService.deleteNovelsByIds(library_id, novelIdsArray);
      setNovels((prev) => prev.filter((novel) => !selectedNovels.has(novel.id)));
      setSelectedNovels(new Set());
    } catch (err) {
      console.error("Failed to delete novels:", err);
      alert("Failed to delete some novels. Please try again.");
    } finally {
      setDeleteLoading(false);
    }
  };

  const selectAll = () => {
    const allIds = processedNovels.map((novel) => novel.id);
    setSelectedNovels(new Set(allIds));
  };

  const deselectAll = () => {
    setSelectedNovels(new Set());
  };

  return (
    <div className={`library-list library-list--${viewMode}`}>
      {loading && (
        <div className="library-list__grid" aria-hidden="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <NovelCardSkeleton key={`skeleton-${i}`} />
          ))}
        </div>
      )}
      {error && (
        <p className="library-list__error" role="alert">
          {error}
        </p>
      )}
      {!loading && processedNovels.length === 0 && !error && (
        <EmptyState
          title={novels.length === 0 ? "No stories in this library yet" : "No stories match these filters"}
          description={novels.length === 0 ? "Add a story from a link to start your library." : "Try another search, shelf, or status."}
        />
      )}

      {processedNovels.length > 0 && (
        <div className="library-list__grid">
          {processedNovels.map((novel) => (
            <LibraryStoryCard
              key={novel.id}
              novel={novel}
              libraryId={library_id}
              compact={viewMode === "list"}
              personalRating={personal[String(novel.id)]?.rating ?? null}
              selectionMode={selectionMode}
              selected={selectedNovels.has(novel.id)}
              onToggleSelect={() => handleNovelClick(novel.id)}
              shelves={shelves}
              onShelvesChanged={onShelvesChanged}
            />
          ))}
        </div>
      )}

      {selectionMode && (
        <div className="library-selection-bar">
          <span>{selectedNovels.size} selected</span>
          <div className="library-selection-bar__actions">
            <button type="button" onClick={selectAll}>
              Select all
            </button>
            <button type="button" onClick={deselectAll}>
              Clear
            </button>
            <button
              type="button"
              className="danger"
              onClick={handleDeleteSelected}
              disabled={selectedNovels.size === 0 || deleteLoading}
            >
              {deleteLoading ? "Deleting…" : "Delete"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default NovelList;
