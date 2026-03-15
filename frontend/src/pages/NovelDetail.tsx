import React, { useEffect, useState, useCallback } from "react";
import defaultCoverImage from "../assets/cover.png";
import { novelService } from "../services/novelService";
import ChapterList from "../components/novel/ChapterList";
import NovelDetails from "../components/novel/NovelDetails";
import { Novel } from "../types/novel";
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
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

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

  const handleUpdateChapters = async () => {
    try {
      setUpdating(true);
      setUpdateMessage("Updating chapters...");

      const updatedNovel = await novelService.updateNovelChapters(
        libraryId,
        novelId
      );

      setNovel(updatedNovel);
      setUpdateMessage("Chapters updated successfully!");

      setTimeout(() => {
        setUpdateMessage(null);
      }, 3000);
    } catch (err) {
      console.error("Failed to update chapters:", err);
      setUpdateMessage("Failed to update chapters");

      setTimeout(() => {
        setUpdateMessage(null);
      }, 5000);
    } finally {
      setUpdating(false);
    }
  };

  const handleRefreshMetadata = async () => {
    try {
      setUpdating(true);
      setUpdateMessage("Refreshing metadata from server...");

      const updatedNovel = await novelService.refreshMetadata(libraryId, novelId);

      setNovel(updatedNovel);
      setUpdateMessage("Metadata refreshed successfully!");

      setTimeout(() => {
        setUpdateMessage(null);
      }, 3000);
    } catch (err) {
      console.error("Failed to refresh metadata:", err);
      setUpdateMessage("Failed to refresh metadata");

      setTimeout(() => {
        setUpdateMessage(null);
      }, 5000);
    } finally {
      setUpdating(false);
    }
  };

  const handleCheckStatus = async () => {
    try {
      setUpdating(true);
      setUpdateMessage("Checking scrape status...");

      const updatedNovel = await novelService.refreshMetadata(libraryId, novelId);

      setNovel(updatedNovel);
      
      if (updatedNovel.scrape_status === "completed") {
        setUpdateMessage("Scrape completed! Metadata updated.");
      } else if (updatedNovel.scrape_status === "failed") {
        setUpdateMessage(`Scrape failed: ${updatedNovel.scrape_error || "Unknown error"}`);
      } else {
        setUpdateMessage("Still scraping... Try again in a few seconds.");
      }

      setTimeout(() => {
        setUpdateMessage(null);
      }, 5000);
    } catch (err) {
      console.error("Failed to check status:", err);
      setUpdateMessage("Failed to check status");

      setTimeout(() => {
        setUpdateMessage(null);
      }, 5000);
    } finally {
      setUpdating(false);
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
      {loading && <p>Loading...</p>}
      {error && <p className="error-message">{error}</p>}
      {!loading && !novel && !error && <p>Novel not found</p>}

      {novel && (
        <div>
          <div className="novel-hero">
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
              <h1 className="novel-hero__title">
                {novel.title}
                {getScrapeStatusIndicator()}
              </h1>
              {novel.author && (
                <p className="novel-hero__author">by {novel.author}</p>
              )}
              {novel.description && (
                <p className="novel-hero__description">{novel.description}</p>
              )}
            </div>
          </div>
          
          <div className="novel-data-holder">
            <div className="novel-details-holder">
              <div className="novel-buttons-holder">
                <h2>Novel Functions</h2>
                <div className="novel-buttons">
                  <button
                    onClick={handleUpdateChapters}
                    disabled={updating}
                    className="update-button"
                  >
                    {updating ? "Updating..." : "Update Chapters"}
                  </button>
                  <button
                    onClick={handleRefreshMetadata}
                    disabled={updating}
                    className="refresh-button"
                  >
                    {updating ? "Refreshing..." : "Refresh Metadata"}
                  </button>
                  {(novel.scrape_status === "pending" || novel.scrape_status === "failed") && (
                    <button
                      onClick={handleCheckStatus}
                      disabled={updating}
                      className="check-status-button"
                    >
                      {updating ? "Checking..." : "Check Scrape Status"}
                    </button>
                  )}
                  {updateMessage && (
                    <p
                      className={`update-message ${
                        updating ? "updating" : "updated"
                      }`}
                    >
                      {updateMessage}
                    </p>
                  )}
                </div>
              </div>
              <NovelDetails novel={novel} />
            </div>
            <ChapterList novel_id={novel.id} library_id={libraryId} />
          </div>
        </div>
      )}
    </div>
  );
};

export default NovelDetail;
