import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { novelService } from "../../services/novelService";
import NovelCard from "./NovelCard";
import "../../styles/novel-list.css";
import { Novel } from "../../types/novel";
import { NovelCardSkeleton } from "../common/Skeleton";

interface NovelListProps {
  library_id: number;
  searchTerm: string;
  sourceFilter: string;
  sortBy: "recent" | "title" | "chapters";
  viewMode: "grid" | "list";
  selectionMode: boolean;
  refreshKey?: number;
}

const NovelList: React.FC<NovelListProps> = ({
  library_id,
  searchTerm,
  sourceFilter,
  sortBy,
  viewMode,
  selectionMode,
  refreshKey = 0,
}) => {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNovels, setSelectedNovels] = useState<Set<number>>(new Set());
  const [deleteLoading, setDeleteLoading] = useState<boolean>(false);
  const navigate = useNavigate();

  useEffect(() => {
    let isCancelled = false;
    const fetchNovels = async () => {
      try {
        setLoading(true);
        const data = await novelService.getAllNovels(library_id, searchTerm);
        if (isCancelled) return;
        if (Array.isArray(data)) {
          setNovels(data);
          setError(null);
        } else {
          setError("Unexpected data format");
        }
      } catch (err) {
        if (!isCancelled) {
          console.error("Failed to fetch novels:", err);
          setError("Failed to load novels");
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
  }, [library_id, searchTerm, refreshKey]);

  useEffect(() => {
    if (!selectionMode) {
      setSelectedNovels(new Set());
    }
  }, [selectionMode]);

  const processedNovels = useMemo(() => {
    const normalizedSource = sourceFilter.toLowerCase();
    const filtered = novels.filter((novel) => {
      if (normalizedSource === "all") return true;
      const site = (novel.novel_site || novel.source_url || "").toLowerCase();
      return site.includes(normalizedSource);
    });

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
  }, [novels, sourceFilter, sortBy]);

  const handleNovelClick = (novelId: number) => {
    if (selectionMode) {
      const updatedSelection = new Set(selectedNovels);
      if (selectedNovels.has(novelId)) {
        updatedSelection.delete(novelId);
      } else {
        updatedSelection.add(novelId);
      }
      setSelectedNovels(updatedSelection);
    } else {
      navigate(`/library/${library_id}/novels/${novelId}`);
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
    <div className={`novel-list novel-list--${viewMode}`}>
      {loading && (
        <div className="novel-list__grid">
          {Array.from({ length: 8 }).map((_, i) => (
            <NovelCardSkeleton key={`skeleton-${i}`} />
          ))}
        </div>
      )}
      {error && <p className="novel-list__status novel-list__status--error">{error}</p>}
      {!loading && processedNovels.length === 0 && !error && (
        <p className="novel-list__status">No novels match your filters.</p>
      )}

      {processedNovels.length > 0 && (
        <div className="novel-list__grid">
          {processedNovels.map((novel) => (
            <div
              key={novel.id}
              className={`novel-card-wrapper ${
                selectionMode && selectedNovels.has(novel.id) ? "is-selected" : ""
              }`}
            >
              {selectionMode && (
                <div className="novel-card-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedNovels.has(novel.id)}
                    onChange={() => handleNovelClick(novel.id)}
                    onClick={(event) => event.stopPropagation()}
                  />
                </div>
              )}
              <NovelCard
                novel={novel}
                isSelected={selectedNovels.has(novel.id)}
                onClick={() => handleNovelClick(novel.id)}
              />
            </div>
          ))}
        </div>
      )}

      {selectionMode && (
        <div className="novel-selection-toolbar">
          <span>{selectedNovels.size} selected</span>
          <div className="novel-selection-toolbar__actions">
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
