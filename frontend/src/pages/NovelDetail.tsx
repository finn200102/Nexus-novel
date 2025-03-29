import React, { useEffect, useState } from "react";
import NovelCard from "../components/novel/NovelCard";
import { novelService } from "../services/novelService";
import ChapterList from "../components/novel/ChapterList";

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

interface NovelDetailProps {
  novelId: number;
  libraryId: number;
}

const NovelDetail: React.FC<NovelDetailProps> = ({ novelId, libraryId }) => {
  const [novel, setNovel] = useState<NovelSchema | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchNovel = async () => {
      try {
        setLoading(true);
        const data = await novelService.getNovelById(libraryId, novelId);

        // Check if we received a valid novel object
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
    };

    fetchNovel();
  }, [libraryId, novelId]);

  return (
    <div>
      {loading && <p>Loading...</p>}
      {error && <p>{error}</p>}
      {!loading && !novel && !error && <p>Novel not found</p>}
      {novel && (
        <NovelCard
          key={novel.id}
          novel={novel}
          isSelected={false}
          onClick={() => {}}
        />
      )}
      {novel && <ChapterList novel_id={novel.id} />}
    </div>
  );
};

export default NovelDetail;
