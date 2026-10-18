import type { ChapterDocument } from "./chapterDocument";
import { offlineImageSource } from "../../services/offlineImageSource";

/** Count approved stored images; a missing source asset must not look ready. */
export function imageReadiness(document?: ChapterDocument) {
  const tags = document?.blocks.flatMap(block => block.html.match(/<img\b[^>]*>/gi) ?? []) ?? [];
  const ready = tags.filter(tag => offlineImageSource(tag) !== null).length;
  const total = Math.max(tags.length, document?.image_assets?.total ?? 0);
  return { ready, total, missing: Math.max(total - ready, document?.image_assets?.missing ?? 0) };
}

export function offlineReadinessLabel(document?: ChapterDocument) {
  const images = imageReadiness(document);
  if (!images.total) return "text ready offline";
  if (images.missing) return `text ready · ${images.ready} of ${images.total} images ready`;
  return `text and ${images.ready} ${images.ready === 1 ? "image" : "images"} ready offline`;
}
