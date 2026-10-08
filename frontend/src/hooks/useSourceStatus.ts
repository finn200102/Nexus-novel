import { useEffect, useState } from "react";
import { sourceStatusService, SourceStatus } from "../services/sourceStatusService";

const REFRESH_MS = 60_000;
let shared: { at: number; promise: Promise<SourceStatus[]> } | null = null;

/** Forget the shared result, e.g. on sign-out or between tests. */
export const resetSourceStatusCache = () => {
  shared = null;
};

const loadShared = (): Promise<SourceStatus[]> => {
  if (!shared || Date.now() - shared.at > REFRESH_MS) {
    const promise = sourceStatusService.list();
    shared = { at: Date.now(), promise };
    promise.catch(() => {
      if (shared?.promise === promise) shared = null;
    });
  }
  return shared.promise;
};

/** Source health for the sites the signed-in user reads from. Shared and refreshed every 60 s. */
export const useSourceStatus = (enabled: boolean): SourceStatus[] => {
  const [sites, setSites] = useState<SourceStatus[]>([]);

  useEffect(() => {
    if (!enabled) {
      resetSourceStatusCache();
      setSites([]);
      return;
    }
    let active = true;
    loadShared()
      .then((list) => { if (active) setSites(list); })
      .catch(() => { if (active) setSites([]); });
    return () => { active = false; };
  }, [enabled]);

  return sites;
};
