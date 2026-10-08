import { beforeEach, describe, expect, it } from "vitest";
import {
  READER_DEFAULTS,
  readGlobalTypography,
  readLayout,
  readStoryOverride,
  resolveTypography,
  writeGlobalTypography,
  writeStoryOverride,
  readAuthorNotesMode,
} from "./readerSettings";

describe("reader settings persistence", () => {
  beforeEach(() => localStorage.clear());

  it("falls back to defaults when nothing is stored", () => {
    expect(readGlobalTypography()).toEqual(READER_DEFAULTS);
    expect(readAuthorNotesMode()).toBe("collapsed");
    expect(readLayout()).toBe("scroll");
  });

  it("ignores invalid stored values", () => {
    localStorage.setItem("nexus-reader-theme", "neon");
    localStorage.setItem("nexus-reader-font-scale", "nope");
    localStorage.setItem("nexus-reader-layout", "carousel");
    expect(readGlobalTypography().theme).toBe("night");
    expect(readGlobalTypography().fontScale).toBe(1);
    expect(readLayout()).toBe("scroll");
  });

  it("round-trips global typography under the existing keys", () => {
    writeGlobalTypography({ fontScale: 1.2, lineHeight: 1.5, contentWidth: 620, theme: "paper" });
    expect(localStorage.getItem("nexus-reader-font-scale")).toBe("1.2");
    expect(readGlobalTypography()).toEqual({ fontScale: 1.2, lineHeight: 1.5, contentWidth: 620, theme: "paper" });
  });

  it("keeps story overrides per novel and lets them win over global values", () => {
    writeGlobalTypography(READER_DEFAULTS);
    writeStoryOverride(7, { fontScale: 1.3, theme: "dusk" });
    expect(localStorage.getItem("nexus-reader-novel-7")).not.toBeNull();
    expect(readStoryOverride(8)).toBeNull();
    const effective = resolveTypography(readGlobalTypography(), readStoryOverride(7));
    expect(effective).toEqual({ ...READER_DEFAULTS, fontScale: 1.3, theme: "dusk" });
  });

  it("removes the story record when the override is cleared", () => {
    writeStoryOverride(7, { fontScale: 1.3 });
    writeStoryOverride(7, null);
    expect(readStoryOverride(7)).toBeNull();
    expect(localStorage.getItem("nexus-reader-novel-7")).toBeNull();
  });

  it("drops malformed story records", () => {
    localStorage.setItem("nexus-reader-novel-3", "{not json");
    expect(readStoryOverride(3)).toBeNull();
    localStorage.setItem("nexus-reader-novel-3", JSON.stringify({ theme: "sepia", fontScale: -2 }));
    expect(readStoryOverride(3)).toBeNull();
  });
});
