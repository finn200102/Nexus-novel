import React, { useEffect, useState, useCallback } from "react";
import { chapterService } from "../../services/chapterService";
import "../../styles/chapter-list.css";
import { useNavigate, useParams } from "react-router-dom";

interface ChapterSchema {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content_status: string;
}

interface ChapterListProps {
  library_id: number;
  novel_id: number;
}

const ChapterList: React.FC<ChapterListProps> = ({ novel_id, library_id }) => {
  const [chapters, setChapters] = useState<ChapterSchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChapterId, setSelectedChapterId] = useState<number | null>(
    null
  );
  const [isEditMode, setIsEditMode] = useState<boolean>(false);
  const [selectedChapters, setSelectedChapters] = useState<number[]>([]);
  const [downloadLoading, setDownloadLoading] = useState<boolean>(false);
  const [deletingLoading, setDeletingLoading] = useState<boolean>(false);
  const { libraryId } = useParams<{ libraryId: string }>();
  const navigate = useNavigate();

  const fetchChapters = useCallback(async () => {
    try {
      setLoading(true);
      const data = await chapterService.getChapters(novel_id);

      console.log("Raw API response:", data);

      if (Array.isArray(data)) {
        const sortedChapters = [...data].sort(
          (a, b) => a.chapter_number - b.chapter_number
        );
        setChapters(sortedChapters);
      } else {
        console.error("Expected array but got:", data);
        setError("Unexpected data format");
      }
    } catch (err) {
      console.error("Failed to fetch chapters:", err);
      setError("Failed to load chapters");
    } finally {
      setLoading(false);
    }
  }, [novel_id]);

  useEffect(() => {
    fetchChapters();
  }, [fetchChapters]);

  const handleChapterClick = (chapter: ChapterSchema) => {
    if (isEditMode) {
      // In edit mode, toggle selection using chapter ID
      setSelectedChapters((prev) =>
        prev.includes(chapter.id)
          ? prev.filter((id) => id !== chapter.id)
          : [...prev, chapter.id]
      );
    } else {
      // In normal mode, navigate to chapter using chapter_number
      setSelectedChapterId(
        chapter.id === selectedChapterId ? null : chapter.id
      );
      navigate(
        `/library/${libraryId}/novels/${novel_id}/${chapter.chapter_number}`
      );
    }
  };

  const toggleEditMode = () => {
    setIsEditMode(!isEditMode);
    if (!isEditMode) {
      setSelectedChapters([]);
    }
  };

  const handleDownloadSelected = async () => {
    if (selectedChapters.length === 0) {
      alert("Please select at least one chapter to download");
      return;
    }

    try {
      setDownloadLoading(true);

      // Get chapter numbers from selected IDs
      const chaptersToDownload = chapters
        .filter((chapter) => selectedChapters.includes(chapter.id))
        .map((chapter) => chapter.chapter_number);

      await chapterService.downloadChapters(
        library_id,
        novel_id,
        chaptersToDownload
      );

      alert("Chapters downloaded successfully");
      setIsEditMode(false);
      setSelectedChapters([]);

      fetchChapters();
    } catch (err) {
      console.error("Failed to download chapters:", err);
      alert("Failed to download chapters");
    } finally {
      setDownloadLoading(false);
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedChapters.length === 0) {
      alert("Please select at least one chapter to delete");
      return;
    }

    try {
      setDeletingLoading(true);

      // Get chapter ids from selected IDs
      const chaptersToDelete = chapters
        .filter((chapter) => selectedChapters.includes(chapter.id))
        .map((chapter) => chapter.id);

      await chapterService.deleteChaptersByIds(chaptersToDelete);

      alert("Chapters deleted successfully");
      setIsEditMode(false);
      setSelectedChapters([]);

      fetchChapters();
    } catch (err) {
      console.error("Failed to delete chapters:", err);
      alert("Failed to delete chapters");
    } finally {
      setDeletingLoading(false);
    }
  };

  return (
    <div className="chapter-list">
      <div className="chapter-list__header">
        <h2 className="chapter-list__title">Chapters</h2>
        <div className="chapter-list__actions">
          <button
            className={`edit-button ${isEditMode ? "active" : ""}`}
            onClick={toggleEditMode}
          >
            {isEditMode ? "Cancel" : "Edit"}
          </button>

          {isEditMode && (
            <button
              className="download-button"
              onClick={handleDownloadSelected}
              disabled={selectedChapters.length === 0 || downloadLoading}
            >
              {downloadLoading ? "Downloading..." : "Download Selected"}
            </button>
          )}
          {isEditMode && (
            <button
              className="delete-button"
              onClick={handleDeleteSelected}
              disabled={selectedChapters.length === 0 || deletingLoading}
            >
              {deletingLoading ? "Deleting..." : "Deleting Selected"}
            </button>
          )}
        </div>
      </div>

      {loading && <p className="chapter-list__loading">Loading...</p>}

      {error && <p className="chapter-list__error">{error}</p>}

      {!loading && chapters.length === 0 && (
        <p className="chapter-list__empty">No chapters found</p>
      )}

      {chapters.length > 0 && (
        <div className="chapter-list__container">
          {chapters.map((chapter) => (
            <div
              key={chapter.id}
              className={`chapter-item ${
                isEditMode
                  ? selectedChapters.includes(chapter.id)
                    ? "chapter-item--selected"
                    : ""
                  : chapter.id === selectedChapterId
                  ? "chapter-item--selected"
                  : ""
              }`}
              onClick={() => handleChapterClick(chapter)}
            >
              {isEditMode && (
                <input
                  type="checkbox"
                  className="chapter-checkbox"
                  checked={selectedChapters.includes(chapter.id)}
                  onChange={() => {}} // Handled by the div click
                />
              )}
              <span className="chapter-number">
                Chapter {chapter.chapter_number}
              </span>
              <span className="chapter-title">
                {chapter.title || "Untitled"}
              </span>
              <span
                className={`chapter-status ${
                  chapter.content_status === "PRESENT"
                    ? "chapter-status--present"
                    : ""
                }`}
              >
                {chapter.content_status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ChapterList;
