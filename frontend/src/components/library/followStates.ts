import type { Novel } from "../../types/novel";

export const FOLLOW_STATE_LABELS: Record<Novel["follow_state"], string> = {
  reading: "Reading",
  plan_to_read: "Plan to read",
  on_hold: "Paused",
  completed: "Finished",
  dropped: "Dropped",
  ignored: "Ignored",
};

/** Where a library card leads: the story page for the copy, or the old reader path if no catalog id. */
export function storyHref(novel: Novel, libraryId: number): string {
  return novel.metadata_id != null
    ? `/story/${novel.metadata_id}?copy=${novel.id}`
    : `/library/${libraryId}/novels/${novel.id}`;
}

