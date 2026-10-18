import {fixtureChapterIdentity as identity} from "../../tests/fixtures/chapterIdentity";
import { describe, expect, it } from "vitest";
import { readerChapterContent, readerChapterDocument } from "./chapterContracts";
const document = () => ({ schema_version: 1, source_format: "html", content_version: "version-1", plain_text: "A note.\nStory.", source_extra: { retained: true },
  blocks: [{ id: "note", kind: "p", html: "<p><em>A note.</em></p>", text: "A note.", role: "author_note", role_provenance: "source" },
    { id: "story", kind: "p", html: '<p>Story.<img src="/private/image" alt="Map"></p>', text: "Story.", source_extra: 42 }] });
describe("chapter wire to reader contracts", () => {
  it("preserves sanitized rich formatting, notes, images, stable IDs and future source metadata", () => {
    const value = document(); const result = readerChapterDocument(value);
    expect(result).toEqual(value); expect(result).not.toBe(value); expect(result?.blocks.map(block => block.id)).toEqual(["note", "story"]);
  });
  it("retains recognizable legacy rich documents without source-format reporting", () => {
    const { source_format: _format, ...legacy } = document(); void _format;
    const legacyBlocks = legacy.blocks.map(({ kind: _kind, ...block }) => { void _kind; return block; });
    const input = { ...legacy, blocks: legacyBlocks }, before = structuredClone({ ...legacy, blocks: legacyBlocks });
    const result = readerChapterDocument(input);
    expect(result?.source_format).toBe("html"); expect(result?.content_version).toBe(legacy.content_version);
    expect(result?.blocks).toEqual(legacyBlocks.map(block => ({ ...block, kind: "unknown" })));
    expect(result?.blocks[1].html).toContain('<img src="/private/image"');
    expect(result?.plain_text).toBe(legacy.plain_text); expect(input).toEqual(before);
    expect(readerChapterDocument({ ...input, source_format: null, blocks: legacyBlocks.map(block => ({ ...block, kind: null })) })?.blocks).toEqual(result?.blocks);
  });
  it("keeps valid rich blocks when optional image reports are sparse or invalid", () => {
    for (const image_assets of [{ ready: 1 }, { total: 1, ready: 1, missing: 0, limited: 0, bytes: 100, failures: { timeout: null } }, null]) {
      const result = readerChapterDocument({ ...document(), image_assets });
      expect(result?.blocks[1].html).toContain('<img src="/private/image"'); expect(result).not.toHaveProperty("image_assets");
    }
    const image_assets = { total: 1, ready: 1, missing: 0, limited: 0, bytes: 100, failures: {} };
    expect(readerChapterDocument({ ...document(), image_assets })?.image_assets).toEqual(image_assets);
  });
  it("omits unsupported optional roles without rewriting markup or unrelated metadata", () => {
    const value = document(); value.blocks[0].role = "future-role"; value.blocks[0].role_provenance = "future-source";
    const result = readerChapterDocument(value);
    expect(result?.blocks[0]).not.toHaveProperty("role"); expect(result?.blocks[0]).not.toHaveProperty("role_provenance");
    expect(result?.blocks[0].html).toBe(value.blocks[0].html); expect(result?.blocks[1]).toHaveProperty("source_extra", 42);
  });
  it("falls back to preserved plain content for missing or unrecognized document cores", () => {
    for (const value of [null, {}, { ...document(), schema_version: 2 }, { ...document(), source_format: "future" }, { ...document(), blocks: [{ id: "broken" }] }, { ...document(), plain_text: null }]) expect(readerChapterDocument(value)).toBeUndefined();
    const result = readerChapterContent({ ...identity(2,3),source_version:"original",current_content_version:"original",id: 1, novel_id: 2, chapter_number: 3, title: "Chapter", content: "Original plain text", document: null });
    expect(result.content).toBe("Original plain text"); expect(result.document).toBeUndefined();
  });
});
