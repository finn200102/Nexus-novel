import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useReaderTypography } from "./useReaderTypography";
import { READER_DEFAULTS, readGlobalTypography, readStoryOverride } from "../components/reader/readerSettings";

describe("useReaderTypography", () => {
  beforeEach(() => localStorage.clear());

  it("saves a change for this story only", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setFontScale(1.2));
    expect(result.current.typography.fontScale).toBe(1.2);
    expect(result.current.hasStoryOverride).toBe(true);
    expect(readStoryOverride(11)).toMatchObject({ fontScale: 1.2 });
    expect(readGlobalTypography()).toEqual(READER_DEFAULTS);
  });

  it("supports updater functions", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setFontScale((value) => value + 0.1));
    expect(result.current.typography.fontScale).toBeCloseTo(1.1);
  });

  it("uses the global value for other stories", () => {
    const first = renderHook(() => useReaderTypography(11));
    act(() => first.result.current.setTheme("paper"));
    const other = renderHook(() => useReaderTypography(12));
    expect(other.result.current.typography.theme).toBe("night");
    expect(other.result.current.hasStoryOverride).toBe(false);
  });

  it("'Use for all stories' promotes the story values to global", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setLineHeight(1.5));
    act(() => result.current.useForAllStories());
    expect(result.current.hasStoryOverride).toBe(false);
    expect(readGlobalTypography().lineHeight).toBe(1.5);
    expect(readStoryOverride(11)).toBeNull();
  });

  it("'Reset to global' drops the story override without touching global", () => {
    const { result } = renderHook(() => useReaderTypography(11));
    act(() => result.current.setContentWidth(620));
    act(() => result.current.resetToGlobal());
    expect(result.current.typography.contentWidth).toBe(READER_DEFAULTS.contentWidth);
    expect(readStoryOverride(11)).toBeNull();
  });
});
