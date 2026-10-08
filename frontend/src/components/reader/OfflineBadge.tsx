import React, { useEffect, useState } from "react";
import { offlineReaderStore } from "../../services/offlineReaderStore";

interface OfflineBadgeProps {
  novelId: number;
  chapterNumber: number;
}

/**
 * Shown while the browser is offline. The reader then serves this chapter
 * from the offline store, and the badge says whether a saved copy exists.
 */
const OfflineBadge: React.FC<OfflineBadgeProps> = ({ novelId, chapterNumber }) => {
  const [online, setOnline] = useState(() => navigator.onLine);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  useEffect(() => {
    let active = true;
    void offlineReaderStore.has(novelId, chapterNumber)
      .then((value) => { if (active) setSaved(value); })
      .catch(() => { if (active) setSaved(false); });
    return () => { active = false; };
  }, [novelId, chapterNumber]);

  if (online) return null;

  return (
    <div className="offline-badge" role="status">
      <strong>Offline</strong>
      <span>{saved ? "Reading the saved copy on this device." : "No saved copy of this chapter."}</span>
    </div>
  );
};

export default OfflineBadge;
