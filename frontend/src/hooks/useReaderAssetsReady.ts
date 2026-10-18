import { useEffect, useState, type RefObject } from "react";

/** Wait for intrinsic image dimensions without letting a damaged asset block reading. */
export function waitForReaderImages(container: HTMLElement, signal: AbortSignal, timeoutMs = 2000): Promise<void> {
  return new Promise(resolve => {
    const pending = new Set(Array.from(container.querySelectorAll<HTMLImageElement>("[data-block-id] img")).filter(image => !image.complete));
    if (!pending.size || signal.aborted) { resolve(); return; }
    const listeners = new Map<HTMLImageElement, () => void>();
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      for (const [image, done] of listeners) {
        image.removeEventListener("load", done); image.removeEventListener("error", done);
      }
      resolve();
    };
    for (const image of pending) {
      const done = () => { pending.delete(image); if (!pending.size) finish(); };
      listeners.set(image, done);
      image.addEventListener("load", done, { once: true });
      image.addEventListener("error", done, { once: true });
    }
    const timer = setTimeout(finish, timeoutMs);
    signal.addEventListener("abort", finish, { once: true });
    // The image may have completed between the initial check and subscription.
    for (const [image, done] of listeners) if (image.complete) done();
  });
}

/** Readiness belongs to a rendition, so an old chapter cannot unlock a new one. */
export function useReaderAssetsReady(contentRef: RefObject<HTMLDivElement | null>, renditionKey: string | null): boolean {
  const [readyKey, setReadyKey] = useState<string | null>(null);
  useEffect(() => {
    const content = contentRef.current;
    if (!content || !renditionKey) return;
    const controller = new AbortController();
    let fontTimer: ReturnType<typeof setTimeout>;
    let finishFonts = () => {};
    const fonts = Promise.race([
      import("../components/reader/readerFonts").then(() => {
        // Trigger layout after loading the font declarations so FontFaceSet
        // includes faces needed by this rendition rather than the prior one.
        content.getBoundingClientRect();
        return document.fonts?.ready;
      }).catch(() => undefined),
      new Promise<void>(resolve => { finishFonts = resolve; fontTimer = setTimeout(resolve, 5000); }),
    ]);
    controller.signal.addEventListener("abort", finishFonts, { once: true });
    void Promise.all([fonts, waitForReaderImages(content, controller.signal)]).then(() => {
      clearTimeout(fontTimer);
      controller.signal.removeEventListener("abort", finishFonts);
      if (!controller.signal.aborted) setReadyKey(renditionKey);
    });
    return () => { controller.abort(); clearTimeout(fontTimer); };
  }, [contentRef, renditionKey]);
  return renditionKey !== null && readyKey === renditionKey;
}
