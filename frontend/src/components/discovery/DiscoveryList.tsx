import React, { useState, useEffect } from "react";
import NovelCard from "../novel/NovelCard";
import { discoveryService } from "../../services/discoveryService";
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
