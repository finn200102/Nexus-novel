import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, CheckCheck, Inbox } from "lucide-react";
import { activityService } from "../../services/activityService";
import type { InboxNovel } from "../../types/activity";

interface UpdatesInboxProps {
  libraryId: number;
  /** Called after an action changed read state, so other views can reload. */
  onChanged?: () => void;
}

const UpdatesInbox: React.FC<UpdatesInboxProps> = ({ libraryId, onChanged }) => {
  const navigate = useNavigate();
  const [rows, setRows] = useState<InboxNovel[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await activityService.getInbox(libraryId));
      setError(null);
    } catch {
      setError("Could not load updates.");
    } finally {
      setLoading(false);
    }
  }, [libraryId]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      onChanged?.();
    } catch {
      setError("That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const readNext = (row: InboxNovel) => {
    if (row.next_unread_chapter_number == null) return;
    navigate(`/library/${libraryId}/novels/${row.novel_id}/${row.next_unread_chapter_number}`);
  };

  return <section className="activity-inbox" aria-labelledby="activity-inbox-title">
    <div className="activity-inbox__header">
      <div className="activity-section__title"><Inbox size={18} /><h2 id="activity-inbox-title">Inbox</h2></div>
      {rows.length > 0 && <button type="button" className="activity-inbox__all" disabled={busy} onClick={() => void run(() => activityService.markAllRead(libraryId))}><CheckCheck size={16} /> Mark all read</button>}
    </div>
    {error && <p className="activity-inbox__error" role="alert">{error}</p>}
    {loading && <p className="activity-page__empty">Loading updates…</p>}
    {!loading && rows.length === 0 && <p className="activity-page__empty">You are all caught up.</p>}
    {!loading && rows.length > 0 && <ul className="activity-inbox__list">
      {rows.map((row) => <li key={row.novel_id} className="activity-inbox__row">
        <div className="activity-inbox__summary">
          <strong>{row.title}</strong>
          <span>— {row.new_chapter_count} new {row.new_chapter_count === 1 ? "chapter" : "chapters"}</span>
        </div>
        <div className="activity-inbox__actions">
          <button type="button" disabled={busy || row.next_unread_chapter_number == null} onClick={() => readNext(row)}><BookOpen size={15} /> Read next</button>
          <button type="button" disabled={busy} onClick={() => void run(() => activityService.markInboxRead(row.novel_id))}>Mark read</button>
          <button type="button" disabled={busy} onClick={() => void run(() => activityService.markInboxCaughtUp(row.novel_id))}>Caught up</button>
        </div>
      </li>)}
    </ul>}
  </section>;
};

export default UpdatesInbox;
