import type { ChapterDocument } from "./chapterDocument";

/** Transient reading view; original identities and note roles stay authoritative. */
export function parallelDocument(original: ChapterDocument, translated: ChapterDocument, language: string): ChapterDocument {
  const byId = new Map(translated.blocks.map(block => [block.id, block]));
  const safeLanguage = /^[a-zA-Z0-9-]{2,20}$/.test(language) ? language : "und";
  const blocks = original.blocks.map(block => {
    const counterpart = byId.get(block.id);
    return { ...block, text: `${block.text}\n\n${counterpart?.text || ""}`,
      html: `<div class="reader-parallel-original">${block.html}</div><div class="reader-parallel-translation" lang="${safeLanguage}">${counterpart?.html || ""}</div>` };
  });
  return { ...original, source_format: "html", blocks, plain_text: blocks.map(block => block.text).join("\n\n") };
}
