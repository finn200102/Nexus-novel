import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ReaderBottomBar from "./ReaderBottomBar";
const base = { totalChapters: 4, percent: 20, minutesLeft: null, paged: false, page: 0, pageCount: 1, hasPrevious: true, hasNext: true, onPrevious: vi.fn(), onNext: vi.fn(), onPreviousPage: vi.fn(), onNextPage: vi.fn() };
describe("reader chapter position", () => {
  it("distinguishes the signed source number from its ordinal", () => {
    render(<ReaderBottomBar {...base} chapterNumber={-2} chapterOrdinal={1} />);
    expect(screen.getByText("Ch. -2 · 1 of 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(base.onNext).toHaveBeenCalledOnce();
  });
  it("does not invent an ordinal or chapter count for a partial index", () => {
    render(<ReaderBottomBar {...base} chapterNumber={20007} chapterOrdinal={null} />);
    expect(screen.getByText("Ch. 20007")).toBeInTheDocument();
    expect(screen.queryByText(/of 20007/)).not.toBeInTheDocument();
  });
  it("keeps chapter zero when paged controls cross a chapter boundary", () => {
    const next = vi.fn();
    render(<ReaderBottomBar {...base} chapterNumber={0} paged onNext={next} hasPrevious={false} />);
    expect(screen.getByText("Page 1 of 1 · Ch. 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous chapter" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next chapter" })); expect(next).toHaveBeenCalledOnce();
  });
});
