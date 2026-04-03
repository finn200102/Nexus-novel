import React, { useEffect, useState, useCallback, useRef } from "react";
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

const DOWNLOAD_WAIT_MS = 500;
const STUCK_PROCESSING_TIMEOUT_MS = 60000;

interface ProcessingChapter {
  id: number;
  startedAt: number;
}

const ChapterList: React.FC<ChapterListProps> = ({ novel_id, library_id }) => {
  const [chapters, setChapters] = useState<ChapterSchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChapterId, setSelectedChapterId] = useState<number | null>(null);
  const [isEditMode, setIsEditMode] = useState<boolean>(false);
  const [selectedChapters, setSelectedChapters] = useState<number[]>([]);
  const [deletingLoading, setDeletingLoading] = useState<boolean>(false);
  const [downloadingChapters, setDownloadingChapters] = useState<Set<number>>(new Set());
  const [processingChapters, setProcessingChapters] = useState<Map<number, number>>(new Map());
  const [showDownloadAllConfirm, setShowDownloadAllConfirm] = useState(false);
  const pollingIntervalRef = useRef<number | null>(null);
  const { libraryId } = useParams<{ libraryId: string }>();
  const navigate = useNavigate();

  const downloadingCount = chapters.filter(c => c.content_status === "PROCESSING").length;
  const failedCount = chapters.filter(c => c.content_status === "FAILED").length;
  const presentCount = chapters.filter(c => c.content_status === "PRESENT").length;
  const totalCount = chapters.length;
  const progressPercent = totalCount > 0 ? Math.round((presentCount / totalCount) * 100) : 0;

  const fetchChapters = useCallback(async () => {
    try {
      const data = await chapterService.getChapters(novel_id);

      if (Array.isArray(data)) {
        const sortedChapters = [...data].sort(
          (a, b) => a.chapter_number - b.chapter_number
        );
        
        const now = Date.now();
        setProcessingChapters((prev) => {
          const updated = new Map(prev);
          
          sortedChapters.forEach((ch) => {
            if (ch.content_status === "PROCESSING") {
              if (!updated.has(ch.id)) {
                updated.set(ch.id, now);
              } else {
                const startedAt = updated.get(ch.id)!;
                if (now - startedAt > STUCK_PROCESSING_TIMEOUT_MS) {
                  chapterService.resetChapterStatus(ch.id, "FAILED").catch((err) => {
                    console.error("Failed to reset chapter status:", err);
                  });
                  updated.delete(ch.id);
                }
              }
            } else {
              updated.delete(ch.id);
            }
          });
          
          const stillDownloading = new Set<number>();
          updated.forEach((_, id) => stillDownloading.add(id));
          setDownloadingChapters(stillDownloading);
          
          return updated;
        });
        
        setChapters(sortedChapters);
      }
    } catch (err) {
      console.error("Failed to fetch chapters:", err);
    }
  }, [novel_id]);

  useEffect(() => {
    fetchChapters();
  }, [fetchChapters]);

  useEffect(() => {
    if (downloadingChapters.size > 0) {
      pollingIntervalRef.current = window.setInterval(() => {
        fetchChapters();
      }, 2000);
    } else if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }

    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, [downloadingChapters.size, fetchChapters]);

  const handleChapterClick = (chapter: ChapterSchema) => {
    if (isEditMode) {
      setSelectedChapters((prev) =>
        prev.includes(chapter.id)
          ? prev.filter((id) => id !== chapter.id)
          : [...prev, chapter.id]
      );
    } else {
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

  const handleDownloadSingle = async (chapterId: number, chapterNumber: number, isRetry: boolean = false) => {
    setDownloadingChapters((prev) => new Set(prev).add(chapterId));
    try {
      if (isRetry) {
        await chapterService.resetChapterStatus(chapterId, "MISSING");
      }
      await chapterService.downloadChapter(library_id, novel_id, chapterNumber);
      fetchChapters();
    } catch (err) {
      console.error("Failed to download chapter:", err);
    }
  };

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  const handleDownloadSelected = async () => {
    if (selectedChapters.length === 0) return;

    const chaptersToDownload = chapters
      .filter((chapter) => selectedChapters.includes(chapter.id))
      .map((chapter) => ({ id: chapter.id, chapter_number: chapter.chapter_number }));

    setIsEditMode(false);
    setSelectedChapters([]);

    for (const chapter of chaptersToDownload) {
      setDownloadingChapters((prev) => new Set(prev).add(chapter.id));
      try {
        await chapterService.downloadChapter(library_id, novel_id, chapter.chapter_number);
      } catch (err) {
        console.error("Failed to download chapter:", chapter.chapter_number, err);
      }
      await sleep(DOWNLOAD_WAIT_MS);
    }
  };

  const handleDownloadAll = async () => {
    setShowDownloadAllConfirm(false);
    
    const missingChapters = chapters
      .filter((chapter) => chapter.content_status === "MISSING" || chapter.content_status === "FAILED")
      .map((chapter) => ({ id: chapter.id, chapter_number: chapter.chapter_number }));

    for (const chapter of missingChapters) {
      setDownloadingChapters((prev) => new Set(prev).add(chapter.id));
      try {
        await chapterService.downloadChapter(library_id, novel_id, chapter.chapter_number);
      } catch (err) {
        console.error("Failed to download chapter:", chapter.chapter_number, err);
      }
      await sleep(DOWNLOAD_WAIT_MS);
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedChapters.length === 0) return;

    try {
      setDeletingLoading(true);

      const chaptersToDelete = chapters
        .filter((chapter) => selectedChapters.includes(chapter.id))
        .map((chapter) => chapter.id);

      await chapterService.deleteChaptersByIds(chaptersToDelete);

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

  const getStatusClass = (status: string) => {
    switch (status) {
      case "PRESENT":
        return "chapter-status--present";
      case "PROCESSING":
        return "chapter-status--processing";
      case "FAILED":
        return "chapter-status--failed";
      default:
        return "";
    }
  };

  const missingCount = chapters.filter(
    (ch) => ch.content_status === "MISSING" || ch.content_status === "FAILED"
  ).length;

  return (
    <div className="chapter-list">
      {!loading && totalCount > 0 && (
        <div className="chapter-download-status">
          <div className="chapter-download-progress">
            <div className="chapter-download-progress-bar">
              <div 
                className="chapter-download-progress-fill" 
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <span className="chapter-download-progress-text">
              {progressPercent}% ({presentCount}/{totalCount})
            </span>
          </div>
          {downloadingCount > 0 && (
            <span className="chapter-download-badge chapter-download-badge--processing">
              {downloadingCount} downloading
            </span>
          )}
          {failedCount > 0 && (
            <span className="chapter-download-badge chapter-download-badge--failed">
              {failedCount} failed
            </span>
          )}
        </div>
      )}

      {showDownloadAllConfirm && (
        <div className="confirm-overlay">
          <div className="confirm-dialog">
            <p>
              You are about to download <strong>{missingCount}</strong> chapters.
            </p>
            <p>This may take a while. Continue?</p>
            <div className="confirm-buttons">
              <button onClick={() => setShowDownloadAllConfirm(false)}>Cancel</button>
              <button onClick={handleDownloadAll} className="confirm-yes">
                Download All
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="chapter-list__header">
        <h2 className="chapter-list__title">
          Chapters {loading ? "" : `(${chapters.length})`}
        </h2>
        <div className="chapter-list__actions">
          {missingCount > 0 && (
            <button
              className="download-all-button"
              onClick={() => {
                if (missingCount > 10) {
                  setShowDownloadAllConfirm(true);
                } else {
                  handleDownloadAll();
                }
              }}
            >
              Download All ({missingCount})
            </button>
          )}

          <button
            className={`edit-button ${isEditMode ? "active" : ""}`}
            onClick={toggleEditMode}
          >
            {isEditMode ? "Cancel" : "Edit"}
          </button>

          {isEditMode && (
            <>
              <button
                className="download-button"
                onClick={handleDownloadSelected}
                disabled={selectedChapters.length === 0}
              >
                Download Selected ({selectedChapters.length})
              </button>
              <button
                className="delete-button"
                onClick={handleDeleteSelected}
                disabled={selectedChapters.length === 0 || deletingLoading}
              >
                {deletingLoading ? "Deleting..." : "Delete Selected"}
              </button>
            </>
          )}
        </div>
      </div>

      {error && <p className="chapter-list__error">{error}</p>}

      {!loading && chapters.length === 0 && (
        <p className="chapter-list__empty">No chapters found</p>
      )}

      {chapters.length > 0 && (
        <div className="chapter-list__container">
          {chapters.map((chapter) => (
            <div key={chapter.id}>
              <div
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
                    onChange={() => {}}
                  />
                )}
                <span className="chapter-number">
                  Chapter {chapter.chapter_number}
                </span>
                <span className="chapter-title">
                  {chapter.title || "Untitled"}
                </span>
                <span className={`chapter-status ${getStatusClass(chapter.content_status)}`}>
                  {chapter.content_status === "PROCESSING" ? "Downloading..." : chapter.content_status}
                </span>
                {!isEditMode && chapter.content_status !== "PRESENT" && chapter.content_status !== "PROCESSING" && (
                  <button
                    className={`download-single-button ${chapter.content_status === "FAILED" ? "download-single-button--retry" : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDownloadSingle(chapter.id, chapter.chapter_number, chapter.content_status === "FAILED");
                    }}
                  >
                    {chapter.content_status === "FAILED" ? "Retry" : "Download"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ChapterList;
