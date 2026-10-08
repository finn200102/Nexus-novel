import { useCallback, useEffect, useState } from "react";
import { activityService } from "../services/activityService";
import type { InboxNovel } from "../types/activity";

/**
 * The single unread-updates source for the bell badge, Home "New chapters"
 * and the Activity inbox. `count` is the number of story groups, the same
 * number the backend reports from `/activity/inbox/count`.
 */
export function useUnreadUpdates(libraryId: number | null | undefined) {
  const [rows, setRows] = useState<InboxNovel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const reload = useCallback(async () => {
    if (libraryId == null) {
      setRows([]);
      return;
    }
    setLoading(true);
    try {
      setRows(await activityService.getInbox(libraryId));
      setError(false);
    } catch {
      setRows([]);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [libraryId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { rows, count: rows.length, loading, error, reload };
}
