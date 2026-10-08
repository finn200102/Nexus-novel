import { describe, expect, it } from "vitest";
import { computePageCount, currentPage, pageScrollLeft, pageStep, scrollPageDelta, scrollPercent } from "./pagedMath";

describe("paged math", () => {
  it("counts pages from the overflow width", () => {
    expect(computePageCount(1000, 500)).toBe(2);
    expect(computePageCount(500, 500)).toBe(1);
    expect(computePageCount(1010, 500)).toBe(2);
    expect(computePageCount(0, 0)).toBe(1);
  });

  it("maps scroll offsets to the nearest page and clamps", () => {
    expect(currentPage(0, 500, 4)).toBe(0);
    expect(currentPage(740, 500, 4)).toBe(1);
    expect(currentPage(9999, 500, 4)).toBe(3);
  });

  it("returns the scroll offset for a page, clamped to range", () => {
    expect(pageScrollLeft(2, 500, 4)).toBe(1000);
    expect(pageScrollLeft(-1, 500, 4)).toBe(0);
    expect(pageScrollLeft(10, 500, 4)).toBe(1500);
  });

  it("moves within the chapter until the first or last page", () => {
    expect(pageStep(0, 3, 1)).toBe("page");
    expect(pageStep(2, 3, 1)).toBe("chapter");
    expect(pageStep(2, 3, -1)).toBe("page");
    expect(pageStep(0, 3, -1)).toBe("chapter");
  });

  it("scrolls by the viewport minus the margin", () => {
    expect(scrollPageDelta(800, 1)).toBe(752);
    expect(scrollPageDelta(800, -1, 100)).toBe(-700);
    expect(scrollPageDelta(10, 1)).toBe(1);
  });

  it("converts offsets to a bounded percentage", () => {
    expect(scrollPercent(50, 200)).toBe(25);
    expect(scrollPercent(500, 200)).toBe(100);
    expect(scrollPercent(0, 0)).toBe(0);
  });
});
