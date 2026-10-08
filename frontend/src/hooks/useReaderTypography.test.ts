import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useReaderTypography } from "./useReaderTypography";
import { READER_DEFAULTS, readGlobalTypography, readStoryOverride } from "../components/reader/readerSettings";

describe("useReaderTypography", () => {
  beforeEach(() => localStorage.clear());

  it("saves changes globally by default", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.set("fontSize", 22));
    expect(result.current.typography.fontSize).toBe(22);
    expect(result.current.storyOnly).toBe(false);
    expect(readGlobalTypography().fontSize).toBe(22);
    expect(readStoryOverride(11)).toBeNull();
  });

  it("supports updater functions", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.set("fontSize", (value) => value + 1));
    expect(result.current.typography.fontSize).toBe(READER_DEFAULTS.fontSize + 1);
  });

  it("'Only for this story' keeps changes on this story", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setStoryOnly(true));
    act(() => result.current.set("theme", "sepia"));
    expect(result.current.typography.theme).toBe("sepia");
    expect(readStoryOverride(11)).toMatchObject({ theme: "sepia" });
    expect(readGlobalTypography().theme).toBe(READER_DEFAULTS.theme);
    const other = renderHook(() => useReaderTypography(12));
    expect(other.result.current.typography.theme).toBe(READER_DEFAULTS.theme);
    expect(other.result.current.storyOnly).toBe(false);
  });

  it("switching 'Only for this story' off returns to the global values", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setStoryOnly(true));
    act(() => result.current.set("width", "wide"));
    act(() => result.current.setStoryOnly(false));
    expect(result.current.typography.width).toBe(READER_DEFAULTS.width);
    expect(readStoryOverride(11)).toBeNull();
  });

  it("'Use for all stories' promotes the story values to global", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setStoryOnly(true));
    act(() => result.current.set("lineHeight", 1.9));
    act(() => result.current.useForAllStories());
    expect(result.current.storyOnly).toBe(false);
    expect(readGlobalTypography().lineHeight).toBe(1.9);
    expect(readStoryOverride(11)).toBeNull();
  });
});
