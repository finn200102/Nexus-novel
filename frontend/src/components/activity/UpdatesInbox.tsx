import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, CheckCheck } from "lucide-react";
import { activityService } from "../../services/activityService";
import { useUnreadUpdates } from "../../hooks/useUnreadUpdates";
import { displayTitle } from "../../utils/displayTitle";
import { Button, EmptyState } from "../ui";
import type { InboxNovel } from "../../types/activity";

interface UpdatesInboxProps {
  libraryId: number;
  /** Called after an action changed read state, so other views can reload. */
  onChanged?: () => void;
}

/** "3 h ago" style label for the story's newest unread chapter. */
const timeAgo = (iso: string): string => {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(minutes)) return "";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
};

const UpdatesInbox: React.FC<UpdatesInboxProps> = ({ libraryId, onChanged }) => {
  const navigate = useNavigate();
  const { rows, loading, error: loadError, reload } = useUnreadUpdates(libraryId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload();
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

  return <section className="updates-inbox" aria-label="New chapters">
    {rows.length > 0 && <div className="updates-inbox__toolbar">
      <Button variant="secondary" size="sm" icon={<CheckCheck size={16} />} disabled={busy} onClick={() => void run(() => activityService.markAllRead(libraryId))}>Mark all read</Button>
    </div>}
    {(error || loadError) && <p className="updates-inbox__error" role="alert">{error ?? "Could not load updates."}</p>}
    {loading && <p className="updates-page__empty">Loading updates…</p>}
    {!loading && rows.length === 0 && <EmptyState level={2} title="You're all caught up." description="New chapters from stories you follow appear here." />}
    {!loading && rows.length > 0 && <ul className="updates-inbox__list">
      {rows.map((row) => <li key={row.novel_id} className="updates-inbox__row">
        <div className="updates-inbox__body">
          <h3 className="updates-inbox__title">{displayTitle({ title: row.title })}</h3>
          <p className="updates-inbox__summary">
            <span>— {row.new_chapter_count} new {row.new_chapter_count === 1 ? "chapter" : "chapters"}</span>
            {row.latest_at && <small> · {timeAgo(row.latest_at)}</small>}
          </p>
        </div>
        <div className="updates-inbox__actions">
          <Button variant="primary" size="sm" icon={<BookOpen size={15} />} disabled={busy || row.next_unread_chapter_number == null} onClick={() => readNext(row)}>Read next</Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void run(() => activityService.markInboxRead(row.novel_id))}>Mark read</Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void run(() => activityService.markInboxCaughtUp(row.novel_id))}>Caught up</Button>
        </div>
      </li>)}
    </ul>}
  </section>;
};

export default UpdatesInbox;
