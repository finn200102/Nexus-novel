import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { novelService } from "../services/novelService";
import { chapterService } from "../services/chapterService";
import { useLibraryContext } from "../context/LibraryContext";
import { useToast } from "../context/ToastContext";
import { Novel } from "../types/novel";
import NovelCard from "../components/novel/NovelCard";
import "../styles/library.css";
import "../styles/novel-list.css";
import "../styles/download-manager.css";

interface NovelDownloadStatus {
  novel: Novel;
  total: number;
  present: number;
  processing: number;
  failed: number;
  processing_chapters: ProcessingChapter[];
  failed_chapters: FailedChapter[];
}

interface ProcessingChapter {
  id: number;
  chapter_number: number;
  title: string | null;
  started_at: string | null;
  retry_count: number;
}

interface FailedChapter {
  id: number;
  chapter_number: number;
  title: string | null;
  error: string | null;
  retry_count: number;
  finished_at: string | null;
}

const Downloads: React.FC = () => {
  const navigate = useNavigate();
  const { activeLibraryId } = useLibraryContext();
  const { addToast } = useToast();

  const [novelStatuses, setNovelStatuses] = useState<NovelDownloadStatus[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [expandedNovel, setExpandedNovel] = useState<number | null>(null);

  const fetchDownloadStatuses = useCallback(async () => {
    if (!activeLibraryId) {
      console.log("DownloadPage: No activeLibraryId");
      return;
    }

    try {
      const novels = await novelService.getAllNovels(activeLibraryId);
      console.log("DownloadPage: Fetched novels:", novels.length);
      const statusesPromises = novels.map(async (novel) => {
        try {
          const status = await chapterService.getDownloadStatus(novel.id);
          console.log("DownloadPage: Status for novel", novel.id, ":", status);
          return {
            novel,
            ...status,
          };
        } catch (err) {
          console.error(`Failed to get status for novel ${novel.id}:`, err);
          return null;
        }
      });

      const statuses = await Promise.all(statusesPromises);
      console.log("DownloadPage: All statuses:", statuses);
      const validStatuses = statuses.filter(
        (s): s is NovelDownloadStatus => s !== null && s.total > 0
      );
      console.log("DownloadPage: Valid statuses:", validStatuses);
      setNovelStatuses(validStatuses);
    } catch (err) {
      console.error("Failed to fetch download statuses:", err);
    } finally {
      setLoading(false);
    }
  }, [activeLibraryId]);

  useEffect(() => {
    fetchDownloadStatuses();
    const interval = setInterval(fetchDownloadStatuses, 3000);
    return () => clearInterval(interval);
  }, [fetchDownloadStatuses]);

  const handleCancelChapter = async (novelId: number, chapterId: number) => {
    try {
      await chapterService.cancelChapterDownload(chapterId);
      fetchDownloadStatuses();
    } catch (err) {
      console.error("Failed to cancel chapter:", err);
      addToast("Failed to cancel chapter", "error");
    }
  };

  const handleCancelAllForNovel = async (novelId: number) => {
    try {
      await chapterService.cancelAllDownloads(novelId);
      fetchDownloadStatuses();
      addToast("All downloads cancelled", "success");
    } catch (err) {
      console.error("Failed to cancel all:", err);
      addToast("Failed to cancel downloads", "error");
    }
  };

  const handleRetryFailed = async (
    novelId: number,
    chapterId: number,
    chapterNumber: number
  ) => {
    try {
      await chapterService.resetChapterStatus(chapterId, "MISSING");
      await chapterService.downloadChapter(activeLibraryId!, novelId, chapterNumber);
      setTimeout(() => fetchDownloadStatuses(), 500);
    } catch (err) {
      console.error("Failed to retry chapter:", err);
      addToast("Failed to retry chapter", "error");
    }
  };

  const handleRetryAllFailed = async (novelId: number, failedChapters: FailedChapter[]) => {
    try {
      for (const chapter of failedChapters) {
        await chapterService.resetChapterStatus(chapter.id, "MISSING");
      }
      fetchDownloadStatuses();
      addToast(`Reset ${failedChapters.length} chapters for retry`, "success");
    } catch (err) {
      console.error("Failed to retry all:", err);
      addToast("Failed to retry chapters", "error");
    }
  };

  const handleNovelClick = (novel: Novel) => {
    navigate(`/library/${activeLibraryId}/novels/${novel.id}`);
  };

  const hasActivity = novelStatuses.some(
    (s) => s.processing > 0 || s.failed > 0
  );

  const getNovelProgress = (status: NovelDownloadStatus) => {
    return status.total > 0
      ? Math.round((status.present / status.total) * 100)
      : 0;
  };

  if (loading) {
    return (
      <div className="library-workspace">
        <header className="library-workspace__header">
          <div>
            <p className="library-workspace__eyebrow">Downloads</p>
            <h1>Download Manager</h1>
          </div>
        </header>
        <div className="discover-loading">Loading download statuses...</div>
      </div>
    );
  }

  return (
    <div className="library-workspace">
      <header className="library-workspace__header">
        <div>
          <p className="library-workspace__eyebrow">Downloads</p>
          <h1>Download Manager</h1>
          <p className="library-workspace__summary">
            Monitor and manage all your chapter downloads across novels.
          </p>
        </div>
      </header>

      {!hasActivity && novelStatuses.length === 0 && (
        <div className="discover-empty">
          <p>No active downloads or downloads with chapters found.</p>
          <p className="discover-empty__hint">
            Start downloading chapters from a novel to see them here.
          </p>
        </div>
      )}

      {novelStatuses.map((status) => {
        const isExpanded = expandedNovel === status.novel.id;
        const progress = getNovelProgress(status);

        return (
          <div key={status.novel.id} className="downloads-novel-card">
            <div
              className="downloads-novel-header"
              onClick={() =>
                setExpandedNovel(isExpanded ? null : status.novel.id)
              }
            >
              <div className="downloads-novel-cover">
                <img
                  src={status.novel.img_url || status.novel.cover_image}
                  alt={status.novel.title}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = "";
                  }}
                />
              </div>
              <div className="downloads-novel-info">
                <h3 className="downloads-novel-title">{status.novel.title}</h3>
                <div className="downloads-novel-meta">
                  <span className="downloads-novel-site">
                    {status.novel.novel_site?.toUpperCase() || "UNKNOWN"}
                  </span>
                  <span className="downloads-novel-count">
                    {status.present}/{status.total} chapters
                  </span>
                  {status.processing > 0 && (
                    <span className="downloads-badge downloads-badge--processing">
                      {status.processing} downloading
                    </span>
                  )}
                  {status.failed > 0 && (
                    <span className="downloads-badge downloads-badge--failed">
                      {status.failed} failed
                    </span>
                  )}
                </div>
                <div className="downloads-progress-bar">
                  <div
                    className="downloads-progress-fill"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
              <div className="downloads-expand-icon">
                {isExpanded ? "▼" : "▶"}
              </div>
            </div>

            {isExpanded && (
              <div className="downloads-novel-content">
                {status.processing > 0 && (
                  <div className="downloads-section">
                    <div className="downloads-section-header">
                      <h4>Downloading ({status.processing})</h4>
                      <button
                        className="downloads-btn downloads-btn--cancel"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancelAllForNovel(status.novel.id);
                        }}
                      >
                        Cancel All
                      </button>
                    </div>
                    <div className="downloads-chapter-list">
                      {status.processing_chapters.map((chapter) => (
                        <div
                          key={chapter.id}
                          className="downloads-chapter-item downloads-chapter-item--processing"
                        >
                          <div className="downloads-chapter-info">
                            <span className="downloads-chapter-number">
                              Ch. {chapter.chapter_number}
                            </span>
                            <span className="downloads-chapter-title">
                              {chapter.title || "Untitled"}
                            </span>
                          </div>
                          <div className="downloads-chapter-actions">
                            <span className="downloads-spinner"></span>
                            <span>Retry #{chapter.retry_count}</span>
                            <button
                              className="downloads-btn downloads-btn--small"
                              onClick={() =>
                                handleCancelChapter(status.novel.id, chapter.id)
                              }
                              title="Cancel"
                            >
                              ✕
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {status.failed > 0 && (
                  <div className="downloads-section">
                    <div className="downloads-section-header">
                      <h4>Failed ({status.failed})</h4>
                      <button
                        className="downloads-btn downloads-btn--retry"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRetryAllFailed(
                            status.novel.id,
                            status.failed_chapters
                          );
                        }}
                      >
                        Retry All Failed
                      </button>
                    </div>
                    <div className="downloads-chapter-list">
                      {status.failed_chapters.map((chapter) => (
                        <div
                          key={chapter.id}
                          className="downloads-chapter-item downloads-chapter-item--failed"
                        >
                          <div className="downloads-chapter-info">
                            <span className="downloads-chapter-number">
                              Ch. {chapter.chapter_number}
                            </span>
                            <span className="downloads-chapter-title">
                              {chapter.title || "Untitled"}
                            </span>
                            {chapter.error && (
                              <span
                                className="downloads-chapter-error"
                                title={chapter.error}
                              >
                                ⚠{" "}
                                {chapter.error.length > 60
                                  ? chapter.error.substring(0, 60) + "..."
                                  : chapter.error}
                              </span>
                            )}
                          </div>
                          <div className="downloads-chapter-actions">
                            <span>Retry #{chapter.retry_count}</span>
                            <button
                              className="downloads-btn downloads-btn--small downloads-btn--retry"
                              onClick={() =>
                                handleRetryFailed(
                                  status.novel.id,
                                  chapter.id,
                                  chapter.chapter_number
                                )
                              }
                              title="Retry"
                            >
                              ↻
                            </button>
                            <button
                              className="downloads-btn downloads-btn--small"
                              onClick={() =>
                                handleCancelChapter(status.novel.id, chapter.id)
                              }
                              title="Cancel"
                            >
                              ✕
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="downloads-novel-actions">
                  <button
                    className="downloads-btn downloads-btn--view"
                    onClick={() => handleNovelClick(status.novel)}
                  >
                    View Novel
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default Downloads;
