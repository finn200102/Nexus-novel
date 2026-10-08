import React, { useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { useSourceStatus } from "../../hooks/useSourceStatus";
import { describeSourceStatus, SourceStatus } from "../../services/sourceStatusService";
import "../../styles/source-status.css";

const DISMISS_KEY = "nexus:source-status-dismissed";

/** Dismissals are per site and state, so a changed state shows again. */
const dismissKey = (status: SourceStatus) => `${status.site}:${status.state}`;

/** Only these states are worth an app-wide line; "degraded" lives in the NovelDetail chip. */
const isBannerState = (status: SourceStatus) => status.state === "rate_limited" || status.state === "down";

const readDismissed = (): Set<string> => {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(DISMISS_KEY) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
};

const writeDismissed = (keys: Set<string>) => {
  try {
    localStorage.setItem(DISMISS_KEY, JSON.stringify([...keys]));
  } catch {
    // Storage refused: the dismissal lasts until the next reload.
  }
};

/** One slim app-wide strip for sites the reader has novels from that are rate-limited or down. */
const SourceStatusBanner: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const sites = useSourceStatus(isAuthenticated);
  const [dismissed, setDismissed] = useState<Set<string>>(readDismissed);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const visible = sites.filter((status) => isBannerState(status) && !dismissed.has(dismissKey(status)));
  if (visible.length === 0) return null;

  const dismissVisible = () => {
    const next = new Set(dismissed);
    visible.forEach((status) => next.add(dismissKey(status)));
    writeDismissed(next);
    setDismissed(next);
    setDetailsOpen(false);
  };

  if (visible.length === 1) {
    const [status] = visible;
    return (
      <div className="source-status-banner" role="status">
        <span className="source-status-banner__text">{describeSourceStatus(status)}</span>
        <button type="button" aria-label={`Dismiss ${status.label} notice`} onClick={dismissVisible}>
          ×
        </button>
      </div>
    );
  }

  return (
    <div className="source-status-banner" role="status">
      <span className="source-status-banner__text">{`${visible.length} sources are having problems`}</span>
      <button type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen((open) => !open)}>
        Details
      </button>
      <button type="button" aria-label="Dismiss source notices" onClick={dismissVisible}>
        ×
      </button>
      {detailsOpen && (
        <ul className="source-status-banner__details">
          {visible.map((status) => (
            <li key={dismissKey(status)}>{describeSourceStatus(status)}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default SourceStatusBanner;
