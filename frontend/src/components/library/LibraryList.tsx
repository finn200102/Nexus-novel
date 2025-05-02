import React, { useState, useEffect } from "react";
import { libraryService } from "../../services/libraryService";
import { useNavigate } from "react-router-dom";
import "../../styles/library-list.css";

interface LibrarySchema {
  id: number;
  name: string;
  user_id: number;
}

const LibraryList: React.FC = () => {
  const [libraries, setLibraries] = useState<LibrarySchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedLibraryId, setSelectedLibraryId] = useState<number | null>(
    null
  );
  const [deleteLoading, setDeleteLoading] = useState<boolean>(false);
  const [editMode, setEditMode] = useState<boolean>(false);
  const [selectedLibraries, setSelectedLibraries] = useState<Set<number>>(
    new Set()
  );
  const navigate = useNavigate();

  useEffect(() => {
    const fetchLibraries = async () => {
      try {
        setLoading(true);
        const data = await libraryService.getLibraries();

        // Ensure we have an array of libraries
        if (Array.isArray(data)) {
          setLibraries(data);
        } else {
          console.error("Expected array but got:", data);
          setError("Unexpected data format");
        }
      } catch (err) {
        console.error("Failed to fetch libraries:", err);
        setError("Failed to load libraries");
      } finally {
        setLoading(false);
      }
    };

    fetchLibraries();
  }, []);

  const toggleEditMode = () => {
    setEditMode(!editMode);
    // Clear selections when exiting edit mode
    if (editMode) {
      setSelectedLibraries(new Set());
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedLibraries.size === 0) return;

    if (
      window.confirm(
        `Are you sure you want to delete ${selectedLibraries.size} selected novels?`
      )
    ) {
      setDeleteLoading(true);

      try {
        // Use the batch delete method
        const novelIdsArray = Array.from(selectedLibraries);
        await libraryService.deleteLibraryByIds(novelIdsArray);

        // Update the libary list by filtering out deleted ones
        setLibraries(
          libraries.filter((library) => !selectedLibraries.has(library.id))
        );
        setSelectedLibraries(new Set());

        // Exit edit mode after deletion
        setEditMode(false);
      } catch (err) {
        console.error("Failed to delete libraries:", err);
        alert("Failed to delete some libaries. Please try again.");
      } finally {
        setDeleteLoading(false);
      }
    }
  };

  const selectAll = () => {
    const allIds = libraries.map((library) => library.id);
    setSelectedLibraries(new Set(allIds));
  };

  const deselectAll = () => {
    setSelectedLibraries(new Set());
  };

  const handleLibraryClick = (libraryId: number) => {
    if (editMode) {
      // In edit mode, toggle selection
      const newSelectedNovels = new Set(selectedLibraries);
      if (selectedLibraries.has(libraryId)) {
        newSelectedNovels.delete(libraryId);
      } else {
        newSelectedNovels.add(libraryId);
      }
      setSelectedLibraries(newSelectedNovels);
    } else {
      // Normal mode, navigate to novel detail
      setSelectedLibraryId(libraryId === selectedLibraryId ? null : libraryId);
      navigate(`/library/${libraryId}`);
    }
  };

  return (
    <div className="library-container">
      <h2 className="library-title">My Libraries</h2>

      {loading && <p className="loading-message">Loading...</p>}

      {error && <p className="error-message">{error}</p>}

      {!loading && libraries.length === 0 && (
        <p className="empty-state-message">No libraries found</p>
      )}

      <div className="library-list__actions">
        <button
          className={`library-list__edit-btn ${editMode ? "active" : ""}`}
          onClick={toggleEditMode}
        >
          {editMode ? "Done" : "Edit"}
        </button>

        {editMode && (
          <>
            <button
              className="library-list__select-all-btn"
              onClick={selectAll}
            >
              Select All
            </button>

            <button
              className="library-list__deselect-all-btn"
              onClick={deselectAll}
            >
              Deselect All
            </button>

            <button
              className="library-list__delete-btn"
              onClick={handleDeleteSelected}
              disabled={selectedLibraries.size === 0 || deleteLoading}
            >
              {deleteLoading
                ? "Deleting..."
                : `Delete (${selectedLibraries.size})`}
            </button>
          </>
        )}
      </div>

      {libraries.length > 0 && (
        <ul className="library-items">
          {libraries.map((library) => (
            <li
              key={library.id}
              onClick={() => handleLibraryClick(library.id)}
              className="library-item"
            >
              {library.name}

              {editMode && (
                <div className="novel-card-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedLibraries.has(library.id)}
                    onChange={() => handleLibraryClick(library.id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default LibraryList;
