import React, { useEffect, useState } from "react";
import { novelService } from "../../services/novelService";
interface NovelSchema {
  id: number;
  title: string;
  url: string;
  library_id: number;
}
interface NovelListProps {
  library_id: number;
}
const NovelList: React.FC<NovelListProps> = ({ library_id }) => {
  const [novels, setNovels] = useState<NovelSchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="novel-list">
      <h2>My Novels</h2>

      {loading && <p>Loading...</p>}

      {error && <p className="error">{error}</p>}

      {!loading && novels.length === 0 && <p>No novels found</p>}

      {novels.length > 0 && (
        <ul>
          {novels.map((novel) => (
            <li key={novel.id}>{novel.title}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default NovelList;
