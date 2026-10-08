import { useEffect, useState } from "react";
import { sourceStatusService, SourceStatus } from "../services/sourceStatusService";

/** How often an open, visible tab re-checks source health. */
const POLL_MS = 60_000;
/** Concurrent consumers (banner, chip) share one request inside this window. */
const SHARE_MS = 30_000;
let shared: { at: number; promise: Promise<SourceStatus[]> } | null = null;

/** Forget the shared result, e.g. on sign-out or between tests. */
export const resetSourceStatusCache = () => {
  shared = null;
};

const loadShared = (): Promise<SourceStatus[]> => {
  if (!shared || Date.now() - shared.at > SHARE_MS) {
    const promise = sourceStatusService.list();
    shared = { at: Date.now(), promise };
    promise.catch(() => {
      if (shared?.promise === promise) shared = null;
    });
  }
  return shared.promise;
};

const isHidden = () => typeof document !== "undefined" && document.visibilityState === "hidden";

/**
 * Source health for the sites the signed-in user reads from. Polled every 60 s
 * while the tab is visible, and refreshed as soon as the tab becomes visible again.
 */
export const useSourceStatus = (enabled: boolean): SourceStatus[] => {
  const [sites, setSites] = useState<SourceStatus[]>([]);

  useEffect(() => {
    if (!enabled) {
      resetSourceStatusCache();
      setSites([]);
      return;
    }
    let active = true;
    const refresh = () => {
      if (isHidden()) return;
      loadShared()
        .then((list) => { if (active) setSites(list); })
        .catch(() => { if (active) setSites([]); });
    };
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [enabled]);

  return sites;
};
