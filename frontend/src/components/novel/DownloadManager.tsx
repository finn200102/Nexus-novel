import React, { useEffect, useState, useCallback } from "react";
import { chapterService } from "../../services/chapterService";
import "../../styles/download-manager.css";

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

interface DownloadStatus {
  total: number;
  present: number;
  missing: number;
  processing: number;
  failed: number;
  processing_chapters: ProcessingChapter[];
  failed_chapters: FailedChapter[];
}

interface DownloadManagerProps {
  novelId: number;
  libraryId: number;
  onDownloadComplete?: () => void;
}

const DownloadManager: React.FC<DownloadManagerProps> = ({ novelId, libraryId, onDownloadComplete }) => {
  const [status, setStatus] = useState<DownloadStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showErrors, setShowErrors] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await chapterService.getDownloadStatus(novelId);
      setStatus(data);
    } catch (err) {
      console.error("Failed to fetch download status:", err);
    }
  }, [novelId]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleCancelChapter = async (chapterId: number) => {
    try {
      await chapterService.cancelChapterDownload(chapterId);
      fetchStatus();
    } catch (err) {
      console.error("Failed to cancel chapter:", err);
    }
  };

  const handleCancelAll = async () => {
    try {
      setLoading(true);
      await chapterService.cancelAllDownloads(novelId);
      fetchStatus();
      onDownloadComplete?.();
    } catch (err) {
      console.error("Failed to cancel all downloads:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleRetryFailed = async (chapterId: number) => {
    try {
      await chapterService.resetChapterStatus(chapterId, "MISSING");
      await chapterService.downloadChapter(libraryId, novelId, status?.failed_chapters.find(c => c.id === chapterId)?.chapter_number || 0);
      fetchStatus();
    } catch (err) {
      console.error("Failed to retry chapter:", err);
    }
  };

  const handleRetryAllFailed = async () => {
    if (!status?.failed_chapters.length) return;
    
    try {
      setLoading(true);
      for (const chapter of status.failed_chapters) {
        await chapterService.resetChapterStatus(chapter.id, "MISSING");
      }
      fetchStatus();
      onDownloadComplete?.();
    } catch (err) {
      console.error("Failed to retry all failed:", err);
    } finally {
      setLoading(false);
    }
  };

  if (!status || status.total === 0) {
    return null;
  }

  const progressPercent = status.total > 0 
    ? Math.round((status.present / status.total) * 100) 
    : 0;

  return (
    <div className="download-manager">
      <div className="download-manager__header" onClick={() => setExpanded(!expanded)}>
        <div className="download-manager__title">
          <span className="download-manager__icon">{expanded ? "▼" : "▶"}</span>
          <span>Download Manager</span>
          {status.present > 0 && (
            <span className="download-manager__badge download-manager__badge--present">
              {status.present} downloaded
            </span>
          )}
          {status.processing > 0 && (
            <span className="download-manager__badge download-manager__badge--processing">
              {status.processing} downloading
            </span>
          )}
          {status.failed > 0 && (
            <span className="download-manager__badge download-manager__badge--failed">
              {status.failed} failed
            </span>
          )}
        </div>
        <div className="download-manager__progress">
          <div className="progress-bar">
            <div 
              className="progress-bar__fill" 
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="progress-text">{progressPercent}% ({status.present}/{status.total})</span>
        </div>
      </div>

      {expanded && (
        <div className="download-manager__content">
          {status.processing > 0 && (
            <div className="download-manager__section">
              <div className="section-header">
                <h4>Downloading ({status.processing})</h4>
                <button 
                  className="cancel-all-btn"
                  onClick={handleCancelAll}
                  disabled={loading}
                >
                  Cancel All
                </button>
              </div>
              <div className="chapter-list">
                {status.processing_chapters.map((chapter) => (
                  <div key={chapter.id} className="chapter-item chapter-item--processing">
                    <div className="chapter-info">
                      <span className="chapter-number">Chapter {chapter.chapter_number}</span>
                      <span className="chapter-title">{chapter.title || "Untitled"}</span>
                    </div>
                    <div className="chapter-status">
                      <span className="spinner"></span>
                      <span>Retry #{chapter.retry_count}</span>
                      <button 
                        className="cancel-btn"
                        onClick={() => handleCancelChapter(chapter.id)}
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
            <div className="download-manager__section">
              <div className="section-header">
                <h4>Failed ({status.failed})</h4>
                <button 
                  className="retry-all-btn"
                  onClick={handleRetryAllFailed}
                  disabled={loading}
                >
                  Retry All Failed
                </button>
              </div>
              <div className="chapter-list">
                {status.failed_chapters.map((chapter) => (
                  <div key={chapter.id} className="chapter-item chapter-item--failed">
                    <div className="chapter-info">
                      <span className="chapter-number">Chapter {chapter.chapter_number}</span>
                      <span className="chapter-title">{chapter.title || "Untitled"}</span>
                      {chapter.error && (
                        <span className="chapter-error" title={chapter.error}>
                          ⚠ {chapter.error.length > 50 ? chapter.error.substring(0, 50) + "..." : chapter.error}
                        </span>
                      )}
                    </div>
                    <div className="chapter-actions">
                      <span className="retry-count">Retry #{chapter.retry_count}</span>
                      <button 
                        className="retry-btn"
                        onClick={() => handleRetryFailed(chapter.id)}
                        title="Retry download"
                      >
                        ↻
                      </button>
                      <button 
                        className="cancel-btn"
                        onClick={() => handleCancelChapter(chapter.id)}
                        title="Cancel and reset"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {status.processing === 0 && status.failed === 0 && status.missing > 0 && (
            <div className="download-manager__section">
              <p className="no-activity">All downloads complete! {status.present} chapters downloaded.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default DownloadManager;
