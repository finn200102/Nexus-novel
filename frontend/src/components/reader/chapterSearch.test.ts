import { describe, expect, it } from "vitest";
import { searchChapter } from "./chapterSearch";

describe("chapter search", () => {
  it("finds long-paragraph matches at their raw offsets", () => {
    const text = "begin ".repeat(1000) + "Exact passage ends here";
    const result = searchChapter([{ id: "long", text }], "exact PASSAGE");
    expect(result.matches[0].textOffset).toBe(6000);
    expect(result.matches[0].locator.textQuote).toContain("Exact passage");
  });
  it("preserves offsets after Unicode case expansion and composed/decomposed accents", () => {
    const text = "İstanbul 😀 cafe\u0301 and CAFÉ";
    const matches = searchChapter([{ id: "unicode", text }], "café").matches;
    expect(matches.map(value => value.textOffset)).toEqual([text.indexOf("cafe"), text.indexOf("CAFÉ")]);
    expect(searchChapter([{ id: "unicode", text }], "CAFÉ", true).matches).toHaveLength(1);
  });
  it("matches phrases across formatting and paragraph whitespace", () => {
    const result = searchChapter([{ id: "a", text: "One last" }, { id: "b", text: "sentence arrives" }], "last sentence");
    expect(result.matches).toHaveLength(1);
    expect(result.matches[0].locator.blockId).toBe("a");
    expect(result.matches[0].textOffset).toBe(4);
  });
  it("bounds output, treats punctuation literally and ignores empty queries", () => {
    expect(searchChapter([{ id: "a", text: "[a] ".repeat(201) }], "[a]").truncated).toBe(true);
    expect(searchChapter([{ id: "a", text: "[a] ".repeat(201) }], "[a]").matches).toHaveLength(200);
    expect(searchChapter([{ id: "a", text: "Anything" }], " ").matches).toHaveLength(0);
  });
  it("retains combining-mark offsets without Intl.Segmenter", () => {
    const original = Intl.Segmenter;
    Object.defineProperty(Intl, "Segmenter", { configurable: true, value: undefined });
    try {
      const result = searchChapter([{ id: "fallback", text: "😀 Cafe\u0301 ends" }], "café");
      expect(result.matches[0].textOffset).toBe(3);
      expect(result.matches[0].endOffset).toBe(8);
    } finally { Object.defineProperty(Intl, "Segmenter", { configurable: true, value: original }); }
  });
});
