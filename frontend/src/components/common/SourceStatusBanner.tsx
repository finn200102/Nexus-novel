import React, { useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { useSourceStatus } from "../../hooks/useSourceStatus";
import { describeSourceStatus, SourceStatus } from "../../services/sourceStatusService";
import "../../styles/source-status.css";

const DISMISS_KEY = "nexus:source-status-dismissed";

const dismissKey = (status: SourceStatus) => `${status.site}:${status.state}`;

const readDismissed = (): Set<string> => {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(DISMISS_KEY) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
};

const writeDismissed = (keys: Set<string>) => {
  try {
    sessionStorage.setItem(DISMISS_KEY, JSON.stringify([...keys]));
  } catch {
    // Storage refused: the dismissal lasts until the next reload.
  }
};

/** App-wide notice for sites the reader has novels from that are not healthy. */
const SourceStatusBanner: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const sites = useSourceStatus(isAuthenticated);
  const [dismissed, setDismissed] = useState<Set<string>>(readDismissed);

  const visible = sites.filter((status) => status.state !== "ok" && !dismissed.has(dismissKey(status)));
  if (visible.length === 0) return null;

  const dismiss = (status: SourceStatus) => {
    const next = new Set(dismissed).add(dismissKey(status));
    writeDismissed(next);
    setDismissed(next);
  };

  return (
    <div className="source-status-banner" role="status">
      {visible.map((status) => (
        <div key={dismissKey(status)} className="source-status-banner__item">
          <span>{describeSourceStatus(status)}</span>
          <button type="button" aria-label={`Dismiss ${status.label} notice`} onClick={() => dismiss(status)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
};

export default SourceStatusBanner;
