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
  description: string;
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
  const [updating, setUpdating] = useState<boolean>(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

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

  const handleUpdateChapters = async () => {
    try {
      setUpdating(true);
      setUpdateMessage("Updating chapters...");

      // Call the update chapters endpoint
      const updatedNovel = await novelService.updateNovelChapters(
        libraryId,
        novelId
      );

      // Update the novel state with the latest data
      setNovel(updatedNovel);
      setUpdateMessage("Chapters updated successfully!");

      // Clear the success message after 3 seconds
      setTimeout(() => {
        setUpdateMessage(null);
      }, 3000);
    } catch (err) {
      console.error("Failed to update chapters:", err);
      setUpdateMessage("Failed to update chapters");

      // Clear the error message after 5 seconds
      setTimeout(() => {
        setUpdateMessage(null);
      }, 5000);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div>
      {loading && <p>Loading...</p>}
      {error && <p className="error-message">{error}</p>}
      {!loading && !novel && !error && <p>Novel not found</p>}

      {novel && (
        <div>
          <div className="novel-header">
            <div>
              <NovelCard
              key={novel.id}
              novel={novel}
              isSelected={false}
              onClick={() => {}}
            />
              <div>
                <h>Description</h>
                <p>
                {novel.description}
              </p>
            </div>

            </div>

            <button
              onClick={handleUpdateChapters}
              disabled={updating}
              className="update-button"
            >
              {updating ? "Updating..." : "Update Chapters"}
            </button>
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
          <ChapterList novel_id={novel.id} library_id={libraryId} />
        </div>
      )}
    </div>
  );
};

export default NovelDetail;
