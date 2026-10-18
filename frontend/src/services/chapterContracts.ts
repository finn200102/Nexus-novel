import type { ChapterContent as WireChapterContent } from "../generated/api";
import type { ChapterBlock, ChapterDocument } from "../components/reader/chapterDocument";

export type ChapterContentResponse = WireChapterContent;
/** Renderer/cache content is narrower than permissive legacy wire documents. */
export type ReaderChapterContent = Omit<WireChapterContent, "document"> & { document?: ChapterDocument };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
function imageReport(value: unknown): ChapterDocument["image_assets"] {
  if (!record(value) || ![value.total, value.ready, value.missing, value.limited, value.bytes].every(count)
      || !record(value.failures) || !Object.values(value.failures).every(count)) return undefined;
  return { total: value.total as number, ready: value.ready as number, missing: value.missing as number,
    limited: value.limited as number, bytes: value.bytes as number, failures: value.failures as Record<string, number> };
}

/** Validate core shape without changing the server's sanitized text or markup.
 * Legacy source-format/kind reporting may be absent; infer presentation-only
 * defaults while retaining original HTML, stable IDs and content fingerprints.
 */
export function readerChapterDocument(value: unknown): ChapterDocument | undefined {
  if (!record(value) || value.schema_version !== 1 || (value.source_format != null && value.source_format !== "text" && value.source_format !== "html")
      || typeof value.content_version !== "string" || typeof value.plain_text !== "string" || !Array.isArray(value.blocks)) return undefined;
  const blocks: ChapterBlock[] = [];
  for (const block of value.blocks) {
    if (!record(block) || typeof block.id !== "string" || (block.kind != null && typeof block.kind !== "string") || typeof block.html !== "string" || typeof block.text !== "string") return undefined;
    const { role, role_provenance, ...extra } = block;
    blocks.push({ ...extra, id: block.id, kind: block.kind ?? "unknown", html: block.html, text: block.text,
      ...(role === "author_note" ? { role } : {}),
      ...(role_provenance === "source" || role_provenance === "heuristic" ? { role_provenance } : {}) });
  }
  const { image_assets, ...extra } = value;
  const assets = imageReport(image_assets);
  return { ...extra, schema_version: 1, source_format: value.source_format ?? "html",
    content_version: value.content_version, plain_text: value.plain_text, blocks, ...(assets ? { image_assets: assets } : {}) };
}

export function readerChapterContent(value: ChapterContentResponse): ReaderChapterContent {
  return { ...value, document: readerChapterDocument(value.document) };
}
