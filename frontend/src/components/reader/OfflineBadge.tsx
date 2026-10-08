import React, { useEffect, useState } from "react";
import { offlineReaderStore } from "../../services/offlineReaderStore";
import { isServerUnreachable, subscribeServerReachability } from "../../services/serverReachability";

interface OfflineBadgeProps {
  novelId: number;
  chapterNumber: number;
}

/**
 * Shown while the browser is offline, or while the server cannot be reached
 * even though the browser reports a connection. The badge says whether a
 * saved copy exists on this device.
 */
const OfflineBadge: React.FC<OfflineBadgeProps> = ({ novelId, chapterNumber }) => {
  const [online, setOnline] = useState(() => navigator.onLine);
  const [saved, setSaved] = useState(false);
  const [unreachable, setUnreachable] = useState(isServerUnreachable);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  useEffect(() => subscribeServerReachability(setUnreachable), []);

  useEffect(() => {
    let active = true;
    void offlineReaderStore.has(novelId, chapterNumber)
      .then((value) => { if (active) setSaved(value); })
      .catch(() => { if (active) setSaved(false); });
    return () => { active = false; };
  }, [novelId, chapterNumber]);

  if (online && !unreachable) return null;

  return (
    <div className="offline-badge" role="status">
      <strong>{online ? "Server unreachable" : "Offline"}</strong>
      <span>{saved ? "Reading the saved copy on this device." : "No saved copy of this chapter."}</span>
    </div>
  );
};

export default OfflineBadge;
