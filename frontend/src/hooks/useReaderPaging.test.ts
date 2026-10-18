import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useReaderPaging } from "./useReaderPaging";

describe("reader paging modal isolation", () => {
  it("does not scroll background prose when Space originates on body during a modal", () => {
    const content = document.createElement("div");
    Object.defineProperties(content, { scrollHeight: { value: 1000 }, clientHeight: { value: 400 } });
    content.scrollBy = vi.fn();
    const next = vi.fn();
    renderHook(() => useReaderPaging({ contentRef: { current: content }, paged: false, layoutKey: "fixture", onPreviousChapter: vi.fn(), onNextChapter: next }));
    const modal = document.createElement("div"); modal.className = "ui-modal-layer";
    document.body.append(modal);
    const space = () => document.body.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true }));
    space(); expect(content.scrollBy).not.toHaveBeenCalled(); expect(next).not.toHaveBeenCalled();
    modal.remove(); space(); expect(content.scrollBy).toHaveBeenCalledTimes(1);
  });
});
