import React, {
  useEffect,
  useState,
  useCallback,
  useRef,
  useSyncExternalStore,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  onAccountStorageChange,
  storageGeneration,
} from "../../services/accountStorage";
import apiClient from "../../services/apiClient";
import { chapterService } from "../../services/chapterService";
import { chapterIdentity } from "../../services/chapterIdentity";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useToast } from "../../context/useToast";
import { Novel } from "../../types/novel";
import type { DownloadJob } from "../../types/activity";
import { downloadService } from "../../services/downloadService";
import defaultCoverImage from "../../assets/cover.png";
import "../../styles/download-manager.css";
import { displayTitle } from "../../utils/displayTitle";
import { EmptyState } from "../ui";

import type { NovelDownloadStatusResponse } from "../../generated/api";
type NovelDownloadStatus = NovelDownloadStatusResponse & { novel: Novel };
type FailedChapter = NovelDownloadStatusResponse["failed_chapters"][number];

interface DownloadsTabProps {
  jobs: DownloadJob[];
  setJobs: React.Dispatch<React.SetStateAction<DownloadJob[]>>;
}

const DownloadsTabContents: React.FC<DownloadsTabProps> = ({
  jobs,
  setJobs,
}) => {
  const navigate = useNavigate();
  const mounted = useRef(false);
  const requestSequence = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const { activeLibraryId } = useLibraryContext();
  const { addToast } = useToast();

  const [novelStatuses, setNovelStatuses] = useState<NovelDownloadStatus[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshError, setRefreshError] = useState("");
  const [statusOffset, setStatusOffset] = useState(0),
    [statusTotal, setStatusTotal] = useState(0);
  const [expandedNovel, setExpandedNovel] = useState<number | null>(null);

  const fetchDownloadStatuses = useCallback(async () => {
    if (!activeLibraryId) {
      console.log("DownloadPage: No activeLibraryId");
      return;
    }

    const request = ++requestSequence.current;
    try {
      const response = await apiClient.get("/chapter/download-status", {
        params: {
          library_id: activeLibraryId,
          offset: statusOffset,
          limit: 100,
        },
      });
      if (!mounted.current || request !== requestSequence.current) return;
      setNovelStatuses(
        response.data.novels.map(
          (row: {
            novel_id: number;
            title: string;
            status: NovelDownloadStatusResponse;
          }) => ({
            ...row.status,
            novel: { id: row.novel_id, title: row.title } as Novel,
          }),
        ),
      );
      setStatusTotal(response.data.total);
      setRefreshError("");
    } catch (err) {
      if (!mounted.current || request !== requestSequence.current) return;
      console.error("Failed to fetch download statuses:", err);
      setRefreshError(
        "Could not refresh download status. Shown information may be out of date. Retry to check your queue.",
      );
    } finally {
      if (mounted.current && request === requestSequence.current)
        setLoading(false);
    }
  }, [activeLibraryId, statusOffset]);

  useEffect(() => {
    fetchDownloadStatuses();
    const interval = setInterval(fetchDownloadStatuses, 3000);
    return () => clearInterval(interval);
  }, [fetchDownloadStatuses]);

  const handleCancelChapter = async (chapterId: number) => {
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
    chapterNumber: number,
  ) => {
    try {
      await retryChapter(novelId, chapterId, chapterNumber);
      setTimeout(() => fetchDownloadStatuses(), 500);
    } catch (err) {
      console.error("Failed to retry chapter:", err);
      addToast("Failed to retry chapter", "error");
    }
  };

  const retryChapter = async (
    novelId: number,
    chapterId: number,
    chapterNumber: number,
  ) => {
    if (!activeLibraryId) throw new Error("Choose a library before retrying.");
    const current = await chapterService.getNavigation(novelId, chapterNumber);
    const identity = chapterIdentity(current);
    if (current.chapter_id !== chapterId || !identity) {
      throw new Error(
        "The chapter list changed. Open the story and review it before retrying.",
      );
    }
    await chapterService.downloadChapter(
      activeLibraryId,
      novelId,
      current.chapter_number,
      identity,
    );
  };

  const handleRetryAllFailed = async (
    novelId: number,
    failedChapters: FailedChapter[],
  ) => {
    try {
      for (const chapter of failedChapters) {
        await retryChapter(novelId, chapter.id, chapter.chapter_number);
      }
      fetchDownloadStatuses();
      addToast(`Retrying ${failedChapters.length} chapters`, "success");
    } catch (err) {
      console.error("Failed to retry all:", err);
      addToast("Failed to retry chapters", "error");
    }
  };

  const handleNovelClick = (novel: Novel) => {
    navigate(`/library/${activeLibraryId}/novels/${novel.id}`);
  };

  const hasActivity = novelStatuses.some(
    (s) => s.processing > 0 || s.failed > 0,
  );

  const updateJob = async (job: DownloadJob, action: "retry" | "cancel") => {
    try {
      const updated =
        action === "retry"
          ? await downloadService.retry(job.id)
          : await downloadService.cancel(job.id);
      setJobs((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (error) {
      console.error(`Failed to ${action} download job`, error);
      addToast(`Failed to ${action} download job`, "error");
    }
  };

  const jobTitle = (job: DownloadJob) => {
    const match = novelStatuses.find((item) => item.novel.id === job.novel_id);
    return match ? displayTitle(match.novel) : `Chapter ${job.chapter_id}`;
  };

  const jobStatusText = (job: DownloadJob) => {
    switch (job.status) {
      case "queued":
        return job.attempt_count > 1 ? "Retrying" : "Waiting";
      case "processing":
        return job.attempt_count > 1 ? "Retrying" : "Saving";
      case "retry_wait":
        return `Retrying · attempt ${job.attempt_count + 1} of ${job.max_attempts}`;
      case "failed":
        return "Failed";
      case "cancelled":
        return "Cancelled";
      default:
        return "Saved";
    }
  };

  const getNovelProgress = (status: NovelDownloadStatus) => {
    return status.total > 0
      ? Math.round((status.present / status.total) * 100)
      : 0;
  };

  if (loading) {
    return <p className="updates-empty">Loading downloads…</p>;
  }

  return (
    <div className="updates-downloads">
      {refreshError && (
        <p role="alert">
          {refreshError}{" "}
          <button onClick={() => void fetchDownloadStatuses()}>
            Retry download status
          </button>
        </p>
      )}
      {statusTotal > 100 && (
        <nav aria-label="Download story pages">
          <button
            disabled={!statusOffset}
            onClick={() => setStatusOffset((value) => Math.max(0, value - 100))}
          >
            Previous download stories
          </button>
          <button
            disabled={statusOffset + 100 >= statusTotal}
            onClick={() => setStatusOffset((value) => value + 100)}
          >
            Next download stories
          </button>
        </nav>
      )}

      {!refreshError && !hasActivity && novelStatuses.length === 0 && (
        <EmptyState
          level={3}
          title="No downloads yet"
          description="Start downloading chapters from a story to see them here."
        />
      )}

      {jobs.length > 0 && (
        <section className="downloads-job-panel" aria-label="Download queue">
          <div className="downloads-section-header">
            <h2>Queue</h2>
            <span>
              {
                jobs.filter((job) =>
                  ["queued", "processing", "retry_wait"].includes(job.status),
                ).length
              }{" "}
              active
            </span>
          </div>
          <div className="downloads-job-list">
            {jobs.slice(0, 25).map((job) => (
              <article key={job.id} className="downloads-job-row">
                <div>
                  <strong>{jobTitle(job)}</strong>
                  <small>{jobStatusText(job)}</small>
                  {job.error && (
                    <small className="downloads-chapter-error">
                      {job.error}
                    </small>
                  )}
                </div>
                <div className="downloads-chapter-actions">
                  {["failed", "cancelled", "retry_wait"].includes(
                    job.status,
                  ) && (
                    <button
                      className="downloads-btn downloads-btn--small downloads-btn--retry"
                      onClick={() => updateJob(job, "retry")}
                    >
                      Retry
                    </button>
                  )}
                  {["queued", "processing", "retry_wait"].includes(
                    job.status,
                  ) && (
                    <button
                      className="downloads-btn downloads-btn--small"
                      onClick={() => updateJob(job, "cancel")}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
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
                  src={
                    status.novel.img_url ||
                    status.novel.cover_image ||
                    defaultCoverImage
                  }
                  alt={displayTitle(status.novel)}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = "";
                  }}
                />
              </div>
              <div className="downloads-novel-info">
                <h3 className="downloads-novel-title">
                  {displayTitle(status.novel)}
                </h3>
                <div className="downloads-novel-meta">
                  <span className="downloads-novel-site">
                    {status.novel.novel_site?.toUpperCase() || ""}
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
                              onClick={() => handleCancelChapter(chapter.id)}
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
                            status.failed_chapters,
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
                                  chapter.chapter_number,
                                )
                              }
                              title="Retry"
                            >
                              ↻
                            </button>
                            <button
                              className="downloads-btn downloads-btn--small"
                              onClick={() => handleCancelChapter(chapter.id)}
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
                    Open story
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

export default function DownloadsTab(props: DownloadsTabProps) {
  const generation = useSyncExternalStore(
    onAccountStorageChange,
    storageGeneration,
  );
  const { activeLibraryId } = useLibraryContext();
  return (
    <DownloadsTabContents key={`${generation}:${activeLibraryId}`} {...props} />
  );
}
