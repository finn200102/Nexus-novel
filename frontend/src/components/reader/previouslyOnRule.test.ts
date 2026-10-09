import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_RECAP_DAYS, daysSince, lastReadParagraphs, markRecapShown, readRecapDays, shouldShowRecap, writeRecapDays,
} from "./previouslyOnRule";

const DAY = 86_400_000;
const now = new Date("2026-10-09T12:00:00Z");
const daysAgo = (n: number) => new Date(now.getTime() - n * DAY).toISOString();

describe("previously-on rule", () => {
  beforeEach(() => window.localStorage.clear());

  it("counts whole days and never goes negative", () => {
    expect(daysSince(daysAgo(7), now)).toBe(7);
    expect(daysSince(daysAgo(6.5), now)).toBe(6);
    expect(daysSince(new Date(now.getTime() + DAY).toISOString(), now)).toBe(0);
  });

  it("shows at the 7-day default threshold but not before", () => {
    expect(readRecapDays()).toBe(DEFAULT_RECAP_DAYS);
    expect(shouldShowRecap({ lastReadAt: daysAgo(6), novelId: 1, thresholdDays: 7, now })).toBe(false);
    expect(shouldShowRecap({ lastReadAt: daysAgo(7), novelId: 1, thresholdDays: 7, now })).toBe(true);
  });

  it("shows at most once per return", () => {
    const lastReadAt = daysAgo(10);
    expect(shouldShowRecap({ lastReadAt, novelId: 1, thresholdDays: 7, now })).toBe(true);
    markRecapShown(1, lastReadAt);
    expect(shouldShowRecap({ lastReadAt, novelId: 1, thresholdDays: 7, now })).toBe(false);
    // A later read creates a new last-read stamp, so the next break is shown again.
    expect(shouldShowRecap({ lastReadAt: daysAgo(8), novelId: 1, thresholdDays: 7, now })).toBe(true);
    // Shown state is per story.
    expect(shouldShowRecap({ lastReadAt, novelId: 2, thresholdDays: 7, now })).toBe(true);
  });

  it("never shows when the setting is off or there is no read yet", () => {
    writeRecapDays(0);
    expect(readRecapDays()).toBe(0);
    expect(shouldShowRecap({ lastReadAt: daysAgo(90), novelId: 1, thresholdDays: 0, now })).toBe(false);
    expect(shouldShowRecap({ lastReadAt: null, novelId: 1, thresholdDays: 7, now })).toBe(false);
  });

  it("falls back to the default for an invalid stored value", () => {
    window.localStorage.setItem("nexus-reader-recap-days", "5");
    expect(readRecapDays()).toBe(DEFAULT_RECAP_DAYS);
  });

  it("returns the paragraphs around the saved position", () => {
    const text = ["one", "two", "three", "four", "five"].join("\n");
    expect(lastReadParagraphs(text, 50)).toEqual(["two", "three"]);
    expect(lastReadParagraphs(text, 0)).toEqual(["one"]);
    expect(lastReadParagraphs("", 50)).toEqual([]);
  });
});
