import { describe, expect, it } from "vitest";
import { isAuthorNoteParagraph, splitAuthorNotes } from "./authorNotes";

describe("isAuthorNoteParagraph", () => {
  it.each([
    "A/N: thanks for reading",
    "AN: quick note",
    "Author's Note: hello",
    "author's note hello",
    "NOTE: sorry for the delay",
    "  a/n with leading space",
  ])("matches %j", (text) => {
    expect(isAuthorNoteParagraph(text)).toBe(true);
  });

  it("does not match ordinary prose", () => {
    expect(isAuthorNoteParagraph("She said nothing at all.")).toBe(false);
    expect(isAuthorNoteParagraph("Announcement came later")).toBe(false);
  });
});

describe("splitAuthorNotes", () => {
  it("detects a leading note run and keeps the body intact", () => {
    const result = splitAuthorNotes(["A/N: pre-chapter words", "Note: more", "", "Body one.", "Body two."]);
    expect(result.head).toEqual(["A/N: pre-chapter words", "Note: more"]);
    expect(result.body).toEqual(["Body one.", "Body two."]);
    expect(result.tail).toEqual([]);
  });

  it("detects a trailing note run", () => {
    const result = splitAuthorNotes(["Body one.", "Body two.", "", "AN: please review"]);
    expect(result.head).toEqual([]);
    expect(result.body).toEqual(["Body one.", "Body two."]);
    expect(result.tail).toEqual(["AN: please review"]);
  });

  it("detects both ends independently", () => {
    const result = splitAuthorNotes(["Author's note: start", "Story text.", "A/N: end"]);
    expect(result.head).toEqual(["Author's note: start"]);
    expect(result.body).toEqual(["Story text."]);
    expect(result.tail).toEqual(["A/N: end"]);
  });

  it("stops the leading run at the first normal paragraph", () => {
    const result = splitAuthorNotes(["Note: one", "Plain paragraph", "Note: two"]);
    expect(result.head).toEqual(["Note: one"]);
    expect(result.body).toEqual(["Plain paragraph"]);
    expect(result.tail).toEqual(["Note: two"]);
  });

  it("returns no notes for ordinary chapters", () => {
    const result = splitAuthorNotes(["First.", "Second."]);
    expect(result).toEqual({ head: [], body: ["First.", "Second."], tail: [] });
  });

  it("handles empty content without throwing", () => {
    expect(splitAuthorNotes([""])).toEqual({ head: [], body: [], tail: [] });
  });
});
