import { afterEach, describe, expect, it } from "vitest";
import { capturePassage } from "./selectedPassage";
import type { ChapterDocument } from "./chapterDocument";

const source = (text: string): ChapterDocument => ({ schema_version: 1, source_format: "html", content_version: "v1", plain_text: text,
  blocks: [{ id: "original", kind: "paragraph", text, html: "" }] });
const fixture = () => {
  const container = document.createElement("div");
  container.innerHTML = '<section data-block-id="original"><p>Before <em>😀 selected</em> after.</p></section><section data-block-id="next"><p>Other paragraph</p></section>';
  document.body.append(container); return container;
};
const select = (start: Node, from: number, end: Node, to: number) => {
  const range = document.createRange(); range.setStart(start, from); range.setEnd(end, to);
  window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
};
afterEach(() => { document.body.innerHTML = ""; window.getSelection()?.removeAllRanges(); });
describe("exact selected passage", () => {
  it("captures Unicode UTF16 offsets across nested formatting without trimming", () => {
    const container = fixture(), text = container.querySelector("em")!.firstChild!;
    select(text, 0, text, 3);
    expect(capturePassage(container, source("Before 😀 selected after."))).toEqual({
      content_version: "v1", block_id: "original", text_offset: 7, text_length: 3, quote: "😀 ",
    });
  });
  it("rejects multi-paragraph selections and mismatched rendered text", () => {
    const container = fixture(), text = container.querySelector("em")!.firstChild!;
    select(text, 0, container.lastElementChild!.firstChild!.firstChild!, 3);
    expect(capturePassage(container, source("Before 😀 selected after."))).toBeNull();
    select(text, 0, text, 2);
    expect(capturePassage(container, source("A translated paragraph"))).toBeNull();
  });
  it("rejects a split surrogate and selections beyond the bound", () => {
    const container = fixture(), text = container.querySelector("em")!.firstChild!;
    select(text, 1, text, 2);
    expect(capturePassage(container, source("Before 😀 selected after."))).toBeNull();
    const block = container.firstElementChild!; block.textContent = "x".repeat(3001);
    select(block.firstChild!, 0, block.firstChild!, 3001);
    expect(capturePassage(container, source(block.textContent))).toBeNull();
  });
});
