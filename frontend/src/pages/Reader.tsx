import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { chapterService } from "../services/chapterService";
import { novelService } from "../services/novelService";
import "../styles/Reader.css";

interface ChapterContent {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
}

interface Novel {
  id: number;
  title: string;
  author: string;
  library_id: number;
  total_chapters: number;
}

const Reader: React.FC = () => {
  const { libraryId, novelId, chapterNumber } = useParams<{
    libraryId: string;
    novelId: string;
    chapterNumber: string;
  }>();
  const navigate = useNavigate();

  const chapter_number = Number(chapterNumber);
  const library_id = Number(libraryId);
  const novel_id = Number(novelId);

  const [chapter, setChapter] = useState<ChapterContent | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const chapterData = await chapterService.getChapterContentByNumber(
          chapter_number,
          library_id,
          novel_id
        );
        setChapter(chapterData);

        if (chapterData && chapterData.novel_id) {
          const novelData = await novelService.getNovelById(
            library_id,
            chapterData.novel_id
          );
          setNovel(novelData);
        }
        setError(null);
      } catch (err) {
        setError("Failed to load content. Please try again later.");
        console.error("Error fetching data:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [chapter_number, library_id, novel_id]);

  const goToChapter = (chapterNumber: number) => {
    navigate(`/library/${library_id}/novels/${novel_id}/${chapterNumber}`);
  };

  if (loading) return <div className="reader-loading">Loading content...</div>;
  if (error) return <div className="reader-error">{error}</div>;
  if (!chapter || !novel)
    return <div className="reader-not-found">Content not found</div>;

  return (
    <div className="reader-container">
      <div className="reader-header">
        <h2 className="novel-title">{novel.title}</h2>
        <h3 className="chapter-title">{chapter.title}</h3>
        <div className="chapter-info">Chapter {chapter.chapter_number}</div>
      </div>

      <div className="reader-content">
        {chapter.content.split("\n").map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>

      <div className="reader-navigation">
        <button
          className="prev-button"
          onClick={() => goToChapter(chapter.chapter_number - 1)}
          disabled={chapter.chapter_number <= 1}
        >
          Previous Chapter
        </button>
        <button
          className="next-button"
          onClick={() => goToChapter(chapter.chapter_number + 1)}
          disabled={chapter.chapter_number >= novel.total_chapters}
        >
          Next Chapter
        </button>
      </div>
    </div>
  );
};

export default Reader;
