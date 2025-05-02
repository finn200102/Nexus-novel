import React, { useState, useEffect } from "react";
import NovelCard from "../novel/NovelCard";
import { discoveryService } from "../../services/discoveryService";
import { novelService } from "../../services/novelService";
import "../../styles/novel-list.css";

interface NovelSchema {
  title: string;
  url: string;
  cover_image: string;
}

interface DiscoveryListProps {
  source: string;
  library_id: number;
}

const DiscoveryList: React.FC<DiscoveryListProps> = ({
  source,
  library_id,
}) => {
  const [novels, setNovels] = useState<NovelSchema[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNovels, setSelectedNovels] = useState<Set<string>>(new Set());
  const [downloadLoading, setDownloadLoading] = useState<boolean>(false);

  useEffect(() => {
    const loadNovels = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await discoveryService.gettrending(source);
        console.log(result);
        setNovels(result);
      } catch (err) {
        setError("Failed to load novels from source: " + source);
      } finally {
        setLoading(false);
      }
    };

    if (source) {
      loadNovels();
    }
  }, [source]);

  const handleNovelClick = (novelUrl: string) => {
    const newSelected = new Set(selectedNovels);

    if (newSelected.has(novelUrl)) {
      newSelected.delete(novelUrl);
    } else {
      newSelected.add(novelUrl);
    }

    setSelectedNovels(newSelected);
  };

  const handleDownloadSelected = async () => {
    if (selectedNovels.size === 0) return;

    if (
      window.confirm(
        `Are you sure you want to download ${selectedNovels.size} selected novels?`
      )
    ) {
      setDownloadLoading(true);

      try {
        // Use the batch delete method
        const novelUrlsArray = Array.from(selectedNovels);
        await novelService.addNovels(library_id, novelUrlsArray);

        setSelectedNovels(new Set());
      } catch (err) {
        console.error("Failed to download novels:", err);
        alert("Failed to download some novels. Please try again.");
      } finally {
        setDownloadLoading(false);
      }
    }
  };

  return (
    <div className="novel-list">
      <div className="novel-list__header">
        <h2 className="novel-list__title">Trending Novels from {source}</h2>
      </div>

      {loading && <p className="novel-list__loading">Loading...</p>}
      {error && <p className="novel-list__error">{error}</p>}
      {!loading && novels.length === 0 && (
        <p className="novel-list__empty">No novels found</p>
      )}
      <div className="discovery-list__actions">
        <button
          className="discovery-list__download-btn"
          onClick={handleDownloadSelected}
          disabled={selectedNovels.size === 0 || downloadLoading}
        >
          {downloadLoading
            ? "Downloading..."
            : `Download (${selectedNovels.size})`}
        </button>
      </div>
      {novels.length > 0 && (
        <div className="novel-list__grid">
          {novels.map((novel) => (
            <div
              key={novel.url}
              className={`novel-card-wrapper ${
                selectedNovels.has(novel.url) ? "selected" : ""
              }`}
            >
              <div className="novel-card-checkbox">
                <input
                  type="checkbox"
                  checked={selectedNovels.has(novel.url)}
                  onChange={() => handleNovelClick(novel.url)}
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
              <NovelCard
                novel={novel}
                isSelected={selectedNovels.has(novel.url)}
                onClick={() => handleNovelClick(novel.url)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default DiscoveryList;
