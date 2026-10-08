import { beforeEach, describe, expect, it } from "vitest";
import {
  GLOBAL_KEY,
  READER_DEFAULTS,
  readAuthorNotesMode,
  readGlobalTypography,
  readLayout,
  readShortcutsEnabled,
  readStoryOverride,
  resolveReaderTheme,
  resolveTypography,
  writeGlobalTypography,
  writeShortcutsEnabled,
  writeStoryOverride,
} from "./readerSettings";

describe("reader settings persistence", () => {
  beforeEach(() => localStorage.clear());

  it("falls back to defaults when nothing is stored", () => {
    expect(readGlobalTypography()).toEqual(READER_DEFAULTS);
    expect(readAuthorNotesMode()).toBe("collapsed");
    expect(readLayout()).toBe("scroll");
    expect(readShortcutsEnabled()).toBe(true);
  });

  it("ignores invalid stored values", () => {
    localStorage.setItem(GLOBAL_KEY, JSON.stringify({ v: 2, theme: "neon", fontSize: "nope", width: "huge", font: "comic" }));
    localStorage.setItem("nexus-reader-layout", "carousel");
    expect(readGlobalTypography()).toEqual(READER_DEFAULTS);
    expect(readLayout()).toBe("scroll");
  });

  it("clamps sizes and snaps spacing to the offered stops", () => {
    localStorage.setItem(GLOBAL_KEY, JSON.stringify({ v: 2, fontSize: 60, lineHeight: 1.75, letterSpacing: 0.07 }));
    const value = readGlobalTypography();
    expect(value.fontSize).toBe(28);
    expect(value.lineHeight).toBe(1.6);
    expect(value.letterSpacing).toBe(0.05);
  });

  it("round-trips global typography and drops the 1.0 keys", () => {
    localStorage.setItem("nexus-reader-font-scale", "1.2");
    const value = { ...READER_DEFAULTS, theme: "black" as const, font: "atkinson" as const, fontSize: 24, justify: true };
    writeGlobalTypography(value);
    expect(readGlobalTypography()).toEqual(value);
    expect(localStorage.getItem("nexus-reader-font-scale")).toBeNull();
  });

  it("keeps story overrides per novel and lets them win over global values", () => {
    writeGlobalTypography(READER_DEFAULTS);
    writeStoryOverride(7, { fontSize: 23, theme: "sepia" });
    expect(readStoryOverride(8)).toBeNull();
    const effective = resolveTypography(readGlobalTypography(), readStoryOverride(7));
    expect(effective).toEqual({ ...READER_DEFAULTS, fontSize: 23, theme: "sepia" });
  });

  it("removes the story record when the override is cleared", () => {
    writeStoryOverride(7, { fontSize: 23 });
    writeStoryOverride(7, null);
    expect(readStoryOverride(7)).toBeNull();
    expect(localStorage.getItem("nexus-reader-novel-7")).toBeNull();
  });

  it("drops malformed story records", () => {
    localStorage.setItem("nexus-reader-novel-3", "{not json");
    expect(readStoryOverride(3)).toBeNull();
    localStorage.setItem("nexus-reader-novel-3", JSON.stringify({ fontScale: -2 }));
    expect(readStoryOverride(3)).toBeNull();
  });

  it("stores the shortcuts switch", () => {
    writeShortcutsEnabled(false);
    expect(readShortcutsEnabled()).toBe(false);
    writeShortcutsEnabled(true);
    expect(readShortcutsEnabled()).toBe(true);
  });

  it("resolves 'match app theme' to Paper or Night", () => {
    expect(resolveReaderTheme("app", "light")).toBe("paper");
    expect(resolveReaderTheme("app", "dark")).toBe("night");
    expect(resolveReaderTheme("sepia", "dark")).toBe("sepia");
  });
});

describe("migration from the 1.0 reader settings", () => {
  beforeEach(() => localStorage.clear());

  it("maps Night/Dusk/Paper to Night/Sepia/Paper", () => {
    for (const [old, next] of [["night", "night"], ["dusk", "sepia"], ["paper", "paper"]]) {
      localStorage.clear();
      localStorage.setItem("nexus-reader-theme", old);
      expect(readGlobalTypography().theme).toBe(next);
    }
  });

  it("keeps the user's size, spacing and width choices", () => {
    localStorage.setItem("nexus-reader-font-scale", "1.2");
    localStorage.setItem("nexus-reader-line-height", "2.1");
    localStorage.setItem("nexus-reader-content-width", "620");
    localStorage.setItem("nexus-reader-theme", "dusk");
    expect(readGlobalTypography()).toEqual({ ...READER_DEFAULTS, fontSize: 23, lineHeight: 1.9, width: "narrow", theme: "sepia" });
  });

  it("maps the 1.0 defaults to the new defaults", () => {
    localStorage.setItem("nexus-reader-font-scale", "1");
    localStorage.setItem("nexus-reader-line-height", "1.8");
    localStorage.setItem("nexus-reader-content-width", "760");
    const value = readGlobalTypography();
    expect(value.fontSize).toBe(19);
    expect(value.lineHeight).toBe(1.6);
    expect(value.width).toBe("medium");
  });

  it("migrates 1.0 story overrides", () => {
    localStorage.setItem("nexus-reader-novel-5", JSON.stringify({ fontScale: 0.85, lineHeight: 1.5, contentWidth: 920, theme: "dusk" }));
    expect(readStoryOverride(5)).toEqual({ fontSize: 16, lineHeight: 1.4, width: "wide", theme: "sepia" });
  });
});
