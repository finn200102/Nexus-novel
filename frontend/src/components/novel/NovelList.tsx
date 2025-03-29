import React, { useEffect, useState } from "react";
import { novelService } from "../../services/novelService";
import NovelCard from "./NovelCard";
import "../../styles/novel-list.css";

interface NovelSchema {
  id: number;
  title: string;
  author_id: number;
  url: string;
  cover_image: string;
  library_id: number;
  created_at: string;
  updated_at: string;
}

interface NovelListProps {
  library_id: number;
}

const NovelList: React.FC<NovelListProps> = ({ library_id }) => {
  const [novels, setNovels] = useState<NovelSchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNovelId, setSelectedNovelId] = useState<number | null>(null);

  useEffect(() => {
    const fetchNovels = async () => {
      try {
        setLoading(true);
        const data = await novelService.getAllNovels(library_id);

        // Ensure we have an array of novels
        if (Array.isArray(data)) {
          setNovels(data);
        } else {
          console.error("Expected array but got:", data);
          setError("Unexpected data format");
        }
      } catch (err) {
        console.error("Failed to fetch novels:", err);
        setError("Failed to load novels");
      } finally {
        setLoading(false);
      }
    };

    fetchNovels();
  }, [library_id]);

  const handleNovelClick = (novelId: number) => {
    setSelectedNovelId(novelId === selectedNovelId ? null : novelId);
  };

  return (
    <div className="novel-list">
      <h2 className="novel-list__title">My Novels</h2>

      {loading && <p className="novel-list__loading">Loading...</p>}

      {error && <p className="novel-list__error">{error}</p>}

      {!loading && novels.length === 0 && (
        <p className="novel-list__empty">No novels found</p>
      )}

      {novels.length > 0 && (
        <div className="novel-list__grid">
          {novels.map((novel) => (
            <NovelCard
              key={novel.id}
              novel={novel}
              isSelected={novel.id === selectedNovelId}
              onClick={() => handleNovelClick(novel.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default NovelList;
