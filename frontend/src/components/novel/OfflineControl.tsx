import React, { useState } from "react";
import { Button, Checkbox } from "../ui";
import { formatBytes, type OfflineCopies } from "./useOfflineCopies";

const BATCH_SIZES = [10, 25, 50] as const;

/** Controls for the copies saved on this device (inside the story page's "Manage offline" sheet). */
const OfflineControl: React.FC<{ offline: OfflineCopies }> = ({ offline }) => {
  const { stored, totalBytes, progress, message, busy, review, reviewBatch, confirmBatch, cancelBatch, removeAll } = offline;
  const [audio, setAudio] = useState(false), [translations, setTranslations] = useState(false);
  return (
    <section className="offline-control" aria-labelledby="offline-control-heading">
      <h3 id="offline-control-heading">Saved on this device</h3>
      <p className="offline-control__summary">
        {stored.length} chapter{stored.length === 1 ? "" : "s"} saved · {formatBytes(totalBytes)}
      </p>
      <p>Next chapters use available downloads, following your current reading position and selected chapter categories. All downloaded chapters includes every category.</p>
      <p>Text includes available embedded images. Optional media copies only recordings and translations already completed on Nexus.</p>
      <Checkbox label="Include completed audio" checked={audio} disabled={busy || !!review} onChange={event => setAudio(event.target.checked)} />
      <Checkbox label="Include completed translations" checked={translations} disabled={busy || !!review} onChange={event => setTranslations(event.target.checked)} />
      <div className="offline-control__actions">
        {BATCH_SIZES.map((count) => (
          <Button key={count} size="sm" variant="secondary" disabled={busy} onClick={() => void reviewBatch("next", count, { audio, translations })}>
            Review next {count}
          </Button>
        ))}
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void reviewBatch("all", 0, { audio, translations })}>
          Review all downloaded chapters
        </Button>
        <Button size="sm" variant="danger" disabled={busy || stored.length === 0} onClick={() => void removeAll()}>
          Remove offline text
        </Button>
      </div>
      {review && <section aria-label="Review offline copies">
        <h4>Review offline copies</h4>
        <p>{review.chapters.length} text chapters · {review.audioCount} recordings · {review.translationCount} translations</p>
        <p>Estimated content to copy: {formatBytes(review.estimatedBytes)}. Embedded images are included in text. Actual browser storage and metadata can differ.</p>
        <p>{review.storage.remaining_bytes === null ? "No account storage limit is set." : `${formatBytes(review.storage.remaining_bytes)} available within your account limit. Replacement copies may use less additional space.`}</p>
        {review.storage.remaining_bytes !== null && review.estimatedBytes > review.storage.remaining_bytes && <p>The estimate exceeds remaining space. Existing copies can be replaced within the limit; new files may need cleanup first.</p>}
        {review.unavailable > 0 && <p>{review.unavailable} chapters are not downloaded on Nexus yet.</p>}
        {review.unknownVersion > 0 && <p>{review.unknownVersion} source versions could not be checked and will be skipped.</p>}
        {review.translationsLimited && <p>At most 20 completed language variants per chapter are included.</p>}
        <Button disabled={busy || !review.chapters.length} onClick={() => void confirmBatch()}>Save reviewed offline copies</Button>
        <Button variant="secondary" disabled={busy} onClick={cancelBatch}>Close offline review</Button>
      </section>}
      {progress && (
        <p role="status" className="offline-control__progress">
          Saving {progress.done} of {progress.total}…
        </p>
      )}
      {!progress && message && <p role="status" className="offline-control__message">{message}</p>}
      {busy && <Button variant="secondary" onClick={cancelBatch}>Stop offline copying</Button>}
    </section>
  );
};

export default OfflineControl;
