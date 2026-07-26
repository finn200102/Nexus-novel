import { describe, expect, it } from "vitest";
import { splitTextForSynthesis } from "../../src/services/ttsService";

describe("splitTextForSynthesis", () => {
  it("keeps ordinary sentences together while bounding provider request sizes", () => {
    const chunks = splitTextForSynthesis("One sentence. Two sentence. Three sentence.", 28);

    expect(chunks).toEqual(["One sentence. Two sentence.", "Three sentence."]);
    expect(chunks.every((chunk) => chunk.length <= 28)).toBe(true);
  });

  it("splits a single oversized sentence so an audio job always advances", () => {
    const chunks = splitTextForSynthesis("abcdefghijkl", 5);

    expect(chunks).toEqual(["abcde", "fghij", "kl"]);
  });

  it("returns no jobs for empty chapter text", () => {
    expect(splitTextForSynthesis("  \n ")).toEqual([]);
  });
});
