import React from "react";
import { Button } from "../ui";
import { formatBytes, type OfflineCopies } from "./useOfflineCopies";

const BATCH_SIZES = [10, 25, 50] as const;

/** Controls for the copies saved on this device (inside the story page's "Manage offline" sheet). */
const OfflineControl: React.FC<{ offline: OfflineCopies }> = ({ offline }) => {
  const { stored, totalBytes, progress, message, busy, saveBatch, removeAll } = offline;
  return (
    <section className="offline-control" aria-labelledby="offline-control-heading">
      <h3 id="offline-control-heading">Saved on this device</h3>
      <p className="offline-control__summary">
        {stored.length} chapter{stored.length === 1 ? "" : "s"} saved · {formatBytes(totalBytes)}
      </p>
      <div className="offline-control__actions">
        {BATCH_SIZES.map((count) => (
          <Button key={count} size="sm" variant="secondary" disabled={busy} onClick={() => void saveBatch("next", count)}>
            Save next {count}
          </Button>
        ))}
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void saveBatch("all", 0)}>
          Save all downloaded chapters
        </Button>
        <Button size="sm" variant="danger" disabled={busy || stored.length === 0} onClick={() => void removeAll()}>
          Remove offline copy
        </Button>
      </div>
      {progress && (
        <p role="status" className="offline-control__progress">
          Saving {progress.done} of {progress.total}…
        </p>
      )}
      {!progress && message && <p role="status" className="offline-control__message">{message}</p>}
    </section>
  );
};

export default OfflineControl;
