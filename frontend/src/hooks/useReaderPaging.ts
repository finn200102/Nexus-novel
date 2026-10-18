import { CSSProperties, RefObject, useCallback, useEffect, useRef, useState } from "react";
import {
  computePageCount,
  currentPage,
  pageScrollLeft,
  pageStep,
  scrollPageDelta,
} from "../components/reader/pagedMath";

const PAGE_PADDING = 24;

interface ReaderPagingOptions {
  contentRef: RefObject<HTMLDivElement | null>;
  paged: boolean;
  /** Changes whenever the text or layout width changes, so page counts are re-measured. */
  layoutKey: string;
  onPreviousChapter: () => void;
  onNextChapter: () => void;
}

const isCoarsePointer = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;

const isTypingTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return false;
  return target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
    || target.isContentEditable
    || target.closest("button, a, [role='button']") !== null;
};

/**
 * Paging for the reader body: CSS-column paged mode, viewport-sized scroll
 * steps, keyboard space / shift-space, and coarse-pointer tap zones.
 */
export function useReaderPaging({ contentRef, paged, layoutKey, onPreviousChapter, onNextChapter }: ReaderPagingOptions) {
  const [pageCount, setPageCount] = useState(1);
  const [page, setPage] = useState(0);
  const [chromeHidden, setChromeHidden] = useState(false);
  const [coarse] = useState(isCoarsePointer);
  const pageRef = useRef(0);
  const countRef = useRef(1);
  const pagedRef = useRef(paged);
  pagedRef.current = paged;
  const chapterCallbacks = useRef({ onPreviousChapter, onNextChapter });
  chapterCallbacks.current = { onPreviousChapter, onNextChapter };

  const measure = useCallback(() => {
    const el = contentRef.current;
    if (!el || !pagedRef.current) return;
    const count = computePageCount(el.scrollWidth, el.clientWidth);
    const now = currentPage(el.scrollLeft, el.clientWidth, count);
    countRef.current = count;
    pageRef.current = now;
    setPageCount(count);
    setPage(now);
  }, [contentRef]);

  useEffect(() => {
    if (!paged) return;
    const el = contentRef.current;
    const frame = window.requestAnimationFrame(measure);
    const onScroll = () => {
      const node = contentRef.current;
      if (!node) return;
      const now = currentPage(node.scrollLeft, node.clientWidth, countRef.current);
      pageRef.current = now;
      setPage(now);
    };
    el?.addEventListener("scroll", onScroll, { passive: true });
    const onImageSettled = (event: Event) => { if (event.target instanceof HTMLImageElement) measure(); };
    el?.addEventListener("load", onImageSettled, true);
    el?.addEventListener("error", onImageSettled, true);
    document.fonts?.addEventListener("loadingdone", measure);
    window.addEventListener("resize", measure);
    return () => {
      window.cancelAnimationFrame(frame);
      el?.removeEventListener("scroll", onScroll);
      el?.removeEventListener("load", onImageSettled, true);
      el?.removeEventListener("error", onImageSettled, true);
      document.fonts?.removeEventListener("loadingdone", measure);
      window.removeEventListener("resize", measure);
    };
  }, [paged, layoutKey, measure, contentRef]);

  const goToPage = useCallback((target: number) => {
    const el = contentRef.current;
    if (!el) return;
    const left = pageScrollLeft(target, el.clientWidth, countRef.current);
    el.scrollTo({ left, behavior: "smooth" });
    pageRef.current = target;
    setPage(target);
  }, [contentRef]);

  /** Moves one page (paged) or one viewport (scroll); at the edges it changes chapter. */
  const advance = useCallback((direction: 1 | -1) => {
    const el = contentRef.current;
    if (!el) return;
    if (pagedRef.current) {
      if (pageStep(pageRef.current, countRef.current, direction) === "chapter") {
        if (direction === 1) chapterCallbacks.current.onNextChapter();
        else chapterCallbacks.current.onPreviousChapter();
      } else {
        goToPage(pageRef.current + direction);
      }
      return;
    }
    const scrollable = el.scrollHeight > el.clientHeight;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
    const atTop = el.scrollTop <= 2;
    if (direction === 1 && atBottom && scrollable) chapterCallbacks.current.onNextChapter();
    else if (direction === -1 && atTop && scrollable) chapterCallbacks.current.onPreviousChapter();
    else el.scrollBy({ top: scrollPageDelta(el.clientHeight, direction), behavior: "smooth" });
  }, [contentRef, goToPage]);

  // Space pages down, shift+space pages up, unless focus is on a control or text field.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== " " || event.ctrlKey || event.metaKey || event.altKey) return;
      if (document.querySelector(".ui-modal-layer")) return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      advance(event.shiftKey ? -1 : 1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [advance]);

  // Tap zones (coarse pointers only): left/right thirds move, the middle toggles
  // the reader bars. Ignored while text is selected so selecting prose still works.
  const onContentClick = useCallback((event: React.MouseEvent<HTMLElement>) => {
    if (!coarse) return;
    const selection = window.getSelection?.();
    if (selection && !selection.isCollapsed && selection.toString().trim()) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = (event.clientX - rect.left) / rect.width;
    if (ratio < 1 / 3) advance(-1);
    else if (ratio > 2 / 3) advance(1);
    else setChromeHidden((value) => !value);
  }, [coarse, advance]);

  const pagedStyle: CSSProperties | undefined = paged
    ? {
        // The container's height comes from the reader layout (between the bars).
        columnCount: 1,
        columnFill: "auto",
        columnGap: `${PAGE_PADDING * 2}px`,
        padding: `0 ${PAGE_PADDING}px`,
        overflowX: "auto",
        overflowY: "hidden",
      }
    : undefined;

  return { page, pageCount, chromeHidden, setChromeHidden, onContentClick, advance, goToPage, pagedStyle };
}
