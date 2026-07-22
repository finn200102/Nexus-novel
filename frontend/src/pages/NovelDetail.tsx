import React, { useEffect, useState, useCallback } from "react";
import defaultCoverImage from "../assets/cover.png";
import { novelService } from "../services/novelService";
import ChapterList from "../components/novel/ChapterList";
import NovelDetails from "../components/novel/NovelDetails";
import { Novel } from "../types/novel";
import { NovelDetailHeroSkeleton } from "../components/common/Skeleton";
import { useToast } from "../context/ToastContext";
import { Bell } from "lucide-react";
import "../styles/novel-detail.css";

interface NovelDetailProps {
  novelId: number;
  libraryId: number;
}

const NovelDetail: React.FC<NovelDetailProps> = ({ novelId, libraryId }) => {
  const [novel, setNovel] = useState<Novel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState<boolean>(false);
  const [updatingFollow, setUpdatingFollow] = useState(false);
  const { addToast } = useToast();
  const fetchNovel = useCallback(async () => {
    try {
      setLoading(true);
      const data = await novelService.getNovelById(libraryId, novelId);

      if (data && typeof data === "object" && "id" in data) {
        setNovel(data);
      } else {
        console.error("Expected novel object but got:", data);
        setError("Unexpected data format");
      }
    } catch (err) {
      console.error("Failed to fetch novel:", err);
      setError("Failed to load novel details");
    } finally {
      setLoading(false);
    }
  }, [libraryId, novelId]);

  useEffect(() => {
    fetchNovel();
  }, [fetchNovel]);

  const handleRefreshMetadata = async () => {
    try {
      setUpdating(true);
      addToast("Refreshing metadata from server...", "info");

      const updatedNovel = await novelService.refreshMetadata(libraryId, novelId);

      setNovel(updatedNovel);
      addToast("Metadata refreshed successfully!", "success");
    } catch (err) {
      console.error("Failed to refresh metadata:", err);
      addToast("Failed to refresh metadata", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleRescrape = async () => {
    try {
      setUpdating(true);
      addToast("Re-scraping novel from source...", "info");

      const updatedNovel = await novelService.rescrapeNovel(libraryId, novelId);

      setNovel(updatedNovel);
      addToast("Re-scrape started! Check status for progress.", "success");
    } catch (err) {
      console.error("Failed to rescrape novel:", err);
      addToast("Failed to rescrape novel", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleCheckStatus = async () => {
    try {
      setUpdating(true);
      addToast("Checking scrape status...", "info");

      const updatedNovel = await novelService.refreshMetadata(libraryId, novelId);

      setNovel(updatedNovel);
      
      if (updatedNovel.scrape_status === "completed") {
        addToast("Scrape completed! Metadata updated.", "success");
      } else if (updatedNovel.scrape_status === "failed") {
        addToast(`Scrape failed: ${updatedNovel.scrape_error || "Unknown error"}`, "error");
      } else {
        addToast("Still scraping... Try again in a few seconds.", "warning");
      }
    } catch (err) {
      console.error("Failed to check status:", err);
      addToast("Failed to check status", "error");
    } finally {
      setUpdating(false);
    }
  };

  const updateFollowState = async (followState: "plan_to_read" | "reading" | "on_hold" | "completed" | "dropped" | "ignored") => {
    try {
      setUpdatingFollow(true);
      const updatedNovel = await novelService.updateFollowState(libraryId, novelId, followState);
      setNovel(updatedNovel);
      addToast(
        followState === "reading" ? "Story marked as reading" : `Story marked as ${followState.replace(/_/g, " ")}`,
        "success"
      );
    } catch (err) {
      console.error("Failed to update follow state:", err);
      addToast("Failed to update follow state", "error");
    } finally {
      setUpdatingFollow(false);
    }
  };

  const getScrapeStatusIndicator = () => {
    if (!novel?.scrape_status || novel.scrape_status === "completed") {
      return null;
    }

    if (novel.scrape_status === "pending") {
      return (
        <span className="scrape-status scrape-status--pending" title="Scraping in progress">
          ⏳
        </span>
      );
    }

    if (novel.scrape_status === "failed") {
      return (
        <span className="scrape-status scrape-status--failed" title={novel.scrape_error || "Scrape failed"}>
          ⚠️
        </span>
      );
    }

    return null;
  };

  const coverImageSrc = novel?.img_url || novel?.cover_image || defaultCoverImage;

  return (
    <div>
      {loading && (
        <div className="novel-detail-wrapper">
          <NovelDetailHeroSkeleton />
        </div>
      )}
      {error && <p className="error-message">{error}</p>}
      {!loading && !novel && !error && <p>Novel not found</p>}

      {novel && (
        <div className="novel-detail-wrapper">
          <div 
            className="novel-hero novel-hero--enhanced" 
            style={{ backgroundImage: `url(${coverImageSrc})` }}
          >
            <div className="novel-hero__cover">
              <img
                src={coverImageSrc}
                alt={`Cover for ${novel.title}`}
                className="novel-hero__image"
                referrerPolicy="no-referrer"
                loading="lazy"
                onError={(e) => {
                  (e.target as HTMLImageElement).src = defaultCoverImage;
                }}
              />
            </div>
            <div className="novel-hero__info">
              <div className="novel-hero__eyebrow">
                <span className="novel-site-badge">
                  {novel.novel_site ? novel.novel_site.toUpperCase() : "UNKNOWN"}
                </span>
                {getScrapeStatusIndicator()}
              </div>
              <h1 className="novel-hero__title">{novel.title}</h1>
              {novel.author && (
                <p className="novel-hero__author">by {novel.author}</p>
              )}
              {novel.description && (
                <p className="novel-hero__description">{novel.description}</p>
              )}
              <div className="novel-hero__cta-row">
                <label className="follow-state-control">
                  <Bell size={17} aria-hidden="true" />
                  <select
                    value={novel.follow_state}
                    disabled={updatingFollow}
                    onChange={(event) => updateFollowState(event.target.value as "plan_to_read" | "reading" | "on_hold" | "completed" | "dropped" | "ignored")}
                    aria-label="Follow state"
                  >
                    <option value="plan_to_read">Plan to read</option>
                    <option value="reading">Reading</option>
                    <option value="on_hold">On hold</option>
                    <option value="completed">Completed</option>
                    <option value="dropped">Dropped</option>
                    <option value="ignored">Ignored</option>
                  </select>
                </label>
                <button
                  onClick={handleRescrape}
                  disabled={updating}
                  className="action-button action-button--primary"
                >
                  {updating ? "Re-scraping..." : "Re-scrape Full"}
                </button>
                <button
                  onClick={handleRefreshMetadata}
                  disabled={updating}
                  className="action-button"
                >
                  {updating ? "Refreshing..." : "Refresh Metadata"}
                </button>
                {(novel.scrape_status === "pending" || novel.scrape_status === "failed") && (
                  <button
                    onClick={handleCheckStatus}
                    disabled={updating}
                    className="action-button action-button--ghost"
                  >
                    {updating ? "Checking..." : "Check Status"}
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="novel-detail-grid">
            <div className="novel-detail-info">
              <NovelDetails novel={novel} />
            </div>
            <div className="novel-detail-chapters">
              <ChapterList novel_id={novel.id} library_id={libraryId} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NovelDetail;
