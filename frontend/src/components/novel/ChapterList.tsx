import React, { useEffect, useState, useCallback } from "react";
import { chapterService } from "../../services/chapterService";
import "../../styles/chapter-list.css";
import { useNavigate } from "react-router-dom";

interface ChapterSchema {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content_status: string;
}

interface ChapterListProps {
  novel_id: number;
}

const ChapterList: React.FC<ChapterListProps> = ({ novel_id }) => {
  const [chapters, setChapters] = useState<ChapterSchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChapterId, setSelectedChapterId] = useState<number | null>(
    null
  );
  const [isEditMode, setIsEditMode] = useState<boolean>(false);
  const [selectedChapters, setSelectedChapters] = useState<number[]>([]);
  const [downloadLoading, setDownloadLoading] = useState<boolean>(false);
  const navigate = useNavigate();

  // Use useCallback to memoize the fetchChapters function
  const fetchChapters = useCallback(async () => {
    try {
      setLoading(true);
      const data = await chapterService.getChapters(novel_id);

      console.log("Raw API response:", data);

      // Ensure we have an array of chapters
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
  }, [novel_id]); // Include novel_id in the dependency array

  useEffect(() => {
    fetchChapters();
  }, [fetchChapters]); // Now fetchChapters is the only dependency

  const handleChapterClick = (chapterId: number) => {
    if (isEditMode) {
      // In edit mode, toggle selection
      setSelectedChapters((prev) =>
        prev.includes(chapterId)
          ? prev.filter((id) => id !== chapterId)
          : [...prev, chapterId]
      );
    } else {
      // In normal mode, navigate to chapter
      setSelectedChapterId(chapterId === selectedChapterId ? null : chapterId);
      navigate(`/novel/${novel_id}/chapter/${chapterId}`);
    }
  };

  const toggleEditMode = () => {
    setIsEditMode(!isEditMode);
    if (!isEditMode) {
      // Entering edit mode, clear selections
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

      await chapterService.downloadChapters(novel_id, chaptersToDownload);

      alert("Chapters downloaded successfully");
      setIsEditMode(false);
      setSelectedChapters([]);

      // Refresh the chapter list to show updated status
      fetchChapters();
    } catch (err) {
      console.error("Failed to download chapters:", err);
      alert("Failed to download chapters");
    } finally {
      setDownloadLoading(false);
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
              onClick={() => handleChapterClick(chapter.id)}
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
