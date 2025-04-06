import React, { useEffect, useState } from "react";
import { novelService } from "../../services/novelService";
import NovelCard from "./NovelCard";
import "../../styles/novel-list.css";
import { useNavigate } from "react-router-dom";

interface NovelSchema {
  id: number;
  title: string;
  author_id: number;
  url: string;
  cover_image: string;
  library_id: number;
  created_at: string;
  updated_at: string;
}

interface NovelListProps {
  library_id: number;
}

const NovelList: React.FC<NovelListProps> = ({ library_id }) => {
  const [novels, setNovels] = useState<NovelSchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNovelId, setSelectedNovelId] = useState<number | null>(null);
  const [editMode, setEditMode] = useState<boolean>(false);
  const [selectedNovels, setSelectedNovels] = useState<Set<number>>(new Set());
  const [deleteLoading, setDeleteLoading] = useState<boolean>(false);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchNovels = async () => {
      try {
        setLoading(true);
        const data = await novelService.getAllNovels(library_id);

        // Ensure we have an array of novels
        if (Array.isArray(data)) {
          setNovels(data);
        } else {
          console.error("Expected array but got:", data);
          setError("Unexpected data format");
        }
      } catch (err) {
        console.error("Failed to fetch novels:", err);
        setError("Failed to load novels");
      } finally {
        setLoading(false);
      }
    };

    fetchNovels();
  }, [library_id]);

  const handleNovelClick = (novelId: number) => {
    if (editMode) {
      // In edit mode, toggle selection
      const newSelectedNovels = new Set(selectedNovels);
      if (selectedNovels.has(novelId)) {
        newSelectedNovels.delete(novelId);
      } else {
        newSelectedNovels.add(novelId);
      }
      setSelectedNovels(newSelectedNovels);
    } else {
      // Normal mode, navigate to novel detail
      setSelectedNovelId(novelId === selectedNovelId ? null : novelId);
      navigate(`/library/${library_id}/novels/${novelId}`);
    }
  };

  const toggleEditMode = () => {
    setEditMode(!editMode);
    // Clear selections when exiting edit mode
    if (editMode) {
      setSelectedNovels(new Set());
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedNovels.size === 0) return;

    if (
      window.confirm(
        `Are you sure you want to delete ${selectedNovels.size} selected novels?`
      )
    ) {
      setDeleteLoading(true);

      try {
        // Use the batch delete method
        const novelIdsArray = Array.from(selectedNovels);
        await novelService.deleteNovelsByIds(library_id, novelIdsArray);

        // Update the novels list by filtering out deleted ones
        setNovels(novels.filter((novel) => !selectedNovels.has(novel.id)));
        setSelectedNovels(new Set());

        // Exit edit mode after deletion
        setEditMode(false);
      } catch (err) {
        console.error("Failed to delete novels:", err);
        alert("Failed to delete some novels. Please try again.");
      } finally {
        setDeleteLoading(false);
      }
    }
  };

  const selectAll = () => {
    const allIds = novels.map((novel) => novel.id);
    setSelectedNovels(new Set(allIds));
  };

  const deselectAll = () => {
    setSelectedNovels(new Set());
  };

  return (
    <div className="novel-list">
      <div className="novel-list__header">
        <h2 className="novel-list__title">My Novels</h2>

        <div className="novel-list__actions">
          <button
            className={`novel-list__edit-btn ${editMode ? "active" : ""}`}
            onClick={toggleEditMode}
          >
            {editMode ? "Done" : "Edit"}
          </button>

          {editMode && (
            <>
              <button
                className="novel-list__select-all-btn"
                onClick={selectAll}
              >
                Select All
              </button>

              <button
                className="novel-list__deselect-all-btn"
                onClick={deselectAll}
              >
                Deselect All
              </button>

              <button
                className="novel-list__delete-btn"
                onClick={handleDeleteSelected}
                disabled={selectedNovels.size === 0 || deleteLoading}
              >
                {deleteLoading
                  ? "Deleting..."
                  : `Delete (${selectedNovels.size})`}
              </button>
            </>
          )}
        </div>
      </div>

      {loading && <p className="novel-list__loading">Loading...</p>}

      {error && <p className="novel-list__error">{error}</p>}

      {!loading && novels.length === 0 && (
        <p className="novel-list__empty">No novels found</p>
      )}

      {novels.length > 0 && (
        <div className="novel-list__grid">
          {novels.map((novel) => (
            <div
              key={novel.id}
              className={`novel-card-wrapper ${
                editMode && selectedNovels.has(novel.id) ? "selected" : ""
              }`}
            >
              {editMode && (
                <div className="novel-card-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedNovels.has(novel.id)}
                    onChange={() => handleNovelClick(novel.id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
              )}
              <NovelCard
                novel={novel}
                isSelected={novel.id === selectedNovelId}
                onClick={() => handleNovelClick(novel.id)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default NovelList;
