import { describe, expect, it } from "vitest";
import { normalizeAnchorText, quoteLocator, resolveTextLocator, selectedTextLocator } from "./chapterDocument";

describe("stable text anchors", () => {
  it("captures a UTF-16 offset in the middle of a long paragraph", () => {
    const text = "Before the saved place. ".repeat(12) + "The reader stopped at this exact passage. " + "After the passage. ".repeat(20);
    const offset = text.indexOf("The reader stopped");
    const blocks = [{ id: "long-paragraph", text }];
    const locator = quoteLocator(blocks, 0, offset);
    expect(locator.textOffset).toBe(offset);
    expect(locator.textQuote).toMatch(/^The reader stopped/);
    expect(resolveTextLocator(blocks, locator)).toEqual({ blockIndex: 0, textOffset: offset, method: "block" });
  });

  it("reanchors after source edits change identifiers and preceding text", () => {
    const old = [{ id: "before", text: "Previous text." }, { id: "old-id", text: "Intro. This exact passage remains in the revised source. Afterwards." }];
    const locator = quoteLocator(old, 1, 7);
    const updated = [{ id: "inserted", text: "New opening." }, { id: "new-id", text: "An expanded introduction. This exact passage remains in the revised source. Afterwards." }];
    expect(resolveTextLocator(updated, locator, false)).toEqual({ blockIndex: 1, textOffset: 26, method: "quote" });
  });

  it("uses neighboring context to distinguish identical paragraphs", () => {
    const text = "The same sentence appears twice.";
    const blocks = [{ id: "before-a", text: "A forest opening with distinctly different context." }, { id: "same-a", text },
      { id: "between", text: "A river scene with a clearly different preceding paragraph." }, { id: "same-b", text }, { id: "after", text: "A ship leaves the quay after this scene." }];
    const locator = quoteLocator(blocks, 3, 0);
    const updated = blocks.map((block, index) => ({ ...block, id: `revised-${index}` }));
    expect(resolveTextLocator(updated, locator, false)).toEqual({ blockIndex: 3, textOffset: 0, method: "quote" });
  });

  it("never silently picks an equally plausible or weakly contextual match", () => {
    const blocks = [{ id: "old", text: "A repeated sentence." }, { id: "another", text: "A repeated sentence." }];
    expect(resolveTextLocator(blocks, { blockId: "old", textOffset: 0, textQuote: "A repeated sentence." }, false)).toEqual({ reason: "ambiguous" });
    expect(resolveTextLocator(blocks, { textQuote: "A repeated", quotePrefix: "." }, false)).toEqual({ reason: "ambiguous" });
  });

  it("maps whitespace normalization back into the actual DOM text offset", () => {
    const blocks = [{ id: "updated", text: "  Intro.\n\t A   saved   passage remains." }];
    expect(resolveTextLocator(blocks, { textQuote: "A saved passage remains." }, false)).toEqual({ blockIndex: 0, textOffset: 11, method: "quote" });
  });

  it("keeps complete Unicode characters at snapshot boundaries", () => {
    const text = "A😀" + "ä".repeat(200);
    const locator = quoteLocator([{ id: "unicode", text }], 0, 2);
    expect(locator.textOffset).toBe(1);
    expect(locator.textQuote).toMatch(/^😀/);
    expect(locator.textQuote!.length).toBeLessThanOrEqual(160);
    expect(normalizeAnchorText("  漢字\n 日本語  ")).toBe("漢字 日本語");
  });

  it("retains a legacy block locator and reports a missing passage", () => {
    expect(resolveTextLocator([{ id: "legacy", text: "Existing text." }], { blockId: "legacy", textOffset: 4 })).toMatchObject({ textOffset: 4, method: "block" });
    expect(resolveTextLocator([{ id: "changed", text: "Rewritten entirely." }], { textQuote: "Deleted passage." }, false)).toEqual({ reason: "missing" });
  });

  it("anchors a selection inside nested emphasis rather than the viewport", () => {
    const container = document.createElement("div");
    container.innerHTML = '<section data-block-id="chosen"><p>Before <em>selected words</em> after.</p></section><p>Outside</p>';
    document.body.append(container);
    const text = container.querySelector("em")!.firstChild!;
    const range = document.createRange(); range.setStart(text, 0); range.setEnd(text, 8);
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
    expect(selectedTextLocator(container)).toMatchObject({ blockId: "chosen", textOffset: 7, textQuote: "selected words after." });
    selection.removeAllRanges(); container.remove();
  });
});
