import { expect, it } from "vitest";
import { parallelDocument } from "./parallelDocument";
import type { ChapterDocument } from "./chapterDocument";

it("pairs by stable identity, retaining original markup and roles without trusting translated note labels", () => {
  const source: ChapterDocument = { schema_version: 1, source_format: "html", content_version: "original", plain_text: "Story. Note.", blocks: [
    { id: "a", kind: "p", html: "<p><em>Story.</em></p>", text: "Story." },
    { id: "b", kind: "p", html: "<p>Note.</p>", text: "Note.", role: "author_note", role_provenance: "source" },
  ] };
  const translated: ChapterDocument = { ...source, blocks: [
    { id: "b", kind: "p", html: "<p>Anmerkung.</p>", text: "Anmerkung." },
    { id: "a", kind: "p", html: "<p>Geschichte.</p>", text: "Geschichte.", role: "author_note" },
  ] };
  const result = parallelDocument(source, translated, 'de" onclick="bad');
  expect(result.blocks[0].html).toContain("<em>Story.</em>");
  expect(result.blocks[0].html).toContain("Geschichte.");
  expect(result.blocks[0].html).toContain('lang="und"');
  expect(result.blocks[0].role).toBeUndefined();
  expect(result.blocks[1].role).toBe("author_note");
  expect(result.blocks[1].id).toBe("b");
});
