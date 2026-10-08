// Pure helpers for paged reading. A "page" is one CSS column of the content
// container; with column-count 1 and padding P, each column step equals the
// container's client width.

export const computePageCount = (scrollWidth: number, clientWidth: number): number => {
  if (clientWidth <= 0) return 1;
  return Math.max(1, Math.round(scrollWidth / clientWidth));
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export const currentPage = (scrollLeft: number, clientWidth: number, pageCount: number): number => {
  if (clientWidth <= 0) return 0;
  return clamp(Math.round(scrollLeft / clientWidth), 0, pageCount - 1);
};

export const pageScrollLeft = (page: number, clientWidth: number, pageCount: number): number =>
  clamp(page, 0, pageCount - 1) * clientWidth;

/** Where a "next" or "previous" press goes: another page, or the neighbouring chapter. */
export const pageStep = (page: number, pageCount: number, direction: 1 | -1): "page" | "chapter" => {
  if (direction === 1) return page < pageCount - 1 ? "page" : "chapter";
  return page > 0 ? "page" : "chapter";
};

/** Viewport-sized scroll distance for scroll-mode paging, keeping a small overlap. */
export const scrollPageDelta = (clientHeight: number, direction: 1 | -1, margin = 48): number =>
  direction * Math.max(1, clientHeight - margin);

/** Percent through the content for either scroll axis (used for saved progress). */
export const scrollPercent = (offset: number, maxOffset: number): number =>
  clamp((offset / Math.max(maxOffset, 1)) * 100, 0, 100);
