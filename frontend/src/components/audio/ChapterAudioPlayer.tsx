import React, { useEffect, useState } from "react";
import { chapterService } from "../../services/chapterService";

interface ChapterAudioPlayerProps {
  libraryId: number;
  novelId: number;
  chapterNumber: number;
}

const ChapterAudioPlayer: React.FC<ChapterAudioPlayerProps> = ({
  libraryId,
  novelId,
  chapterNumber,
}) => {
  const [audioSrc, setAudioSrc] = useState<string>(); // object‑URL
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!chapterNumber) return;

    let urlToRevoke: string | undefined;
    (async () => {
      try {
        setLoading(true);
        const src = await chapterService.getChapterAudio(
          libraryId,
          novelId,
          chapterNumber
        );
        urlToRevoke = src;
        setAudioSrc(src);
        setError(undefined);
      } catch (err) {
        console.error(err);
        setError("Audio could not be loaded.");
      } finally {
        setLoading(false);
      }
    })();

    // Clean up: revoke object‑URL when component unmounts or chapter changes
    return () => {
      if (urlToRevoke) URL.revokeObjectURL(urlToRevoke);
    };
  }, [libraryId, novelId, chapterNumber]);

  if (!chapterNumber) return null;
  if (loading) return <p>Loading audio…</p>;
  if (error) return <p>{error}</p>;
  if (!audioSrc) return null; // nothing yet

  return (
    <div className="audio-player">
      <h3>Audio Player</h3>
      <audio controls src={audioSrc} preload="metadata" />
    </div>
  );
};

export default ChapterAudioPlayer;
