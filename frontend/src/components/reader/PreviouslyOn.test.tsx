import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PreviouslyOn from "./PreviouslyOn";
import { RECAP_DAYS_KEY } from "./previouslyOnRule";

const getSpoilerSafeRecap = vi.fn();
vi.mock("../../services/chapterService", () => ({
  chapterService: { getSpoilerSafeRecap: (...args: unknown[]) => getSpoilerSafeRecap(...args) },
}));

const DAY = 86_400_000;
const longAgo = new Date(Date.now() - 10 * DAY).toISOString();
const chapter = { chapter_number: 4, title: "The Gate", content: "A\nB\nC\nD\nE" };

describe("PreviouslyOn", () => {
  beforeEach(() => {
    window.localStorage.clear();
    getSpoilerSafeRecap.mockReset();
    getSpoilerSafeRecap.mockRejectedValue(new Error("offline"));
  });

  it("shows the last-time fallback, focuses the heading, and closes on Escape", async () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: longAgo }} chapter={chapter} />);

    expect(await screen.findByRole("heading", { name: /previously on/i })).toHaveFocus();
    expect(screen.getByText(/Last time: Chapter 4 — The Gate, 10 days ago/)).toBeInTheDocument();
    expect(screen.getByText("C")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("heading", { name: /previously on/i })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("uses the stored recap when chapters exist", async () => {
    getSpoilerSafeRecap.mockResolvedValue({
      summary: "x", spoiler_boundary_chapter: 4, chapters: [{ number: 3, title: "Arrival" }, { number: 4, title: "The Gate" }],
    });
    render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: longAgo }} chapter={chapter} />);
    expect(await screen.findByText(/up to chapter 4/i)).toBeInTheDocument();
    expect(screen.getByText("3. Arrival")).toBeInTheDocument();
  });

  it.each([0,-3])("preserves signed recap boundary %s",async boundary=>{
    getSpoilerSafeRecap.mockResolvedValue({summary:"Verified recap",spoiler_boundary_chapter:boundary,chapters:[{number:boundary,title:"A prologue"}]});
    render(<PreviouslyOn novelId={1} progress={{chapter_number:4,percent:50,updated_at:longAgo}} chapter={chapter}/>);
    expect(await screen.findByText(new RegExp(`up to chapter ${boundary}`))).toBeInTheDocument();
  });

  it("does not present chapter entries without a verified boundary",async()=>{
    getSpoilerSafeRecap.mockResolvedValue({summary:"Unverified",spoiler_boundary_chapter:null,chapters:[{number:4,title:"UNVERIFIED_FUTURE_TITLE"}]});
    await act(async()=>{render(<PreviouslyOn novelId={1} progress={{chapter_number:4,percent:50,updated_at:longAgo}} chapter={chapter}/>);});
    await screen.findByRole("heading",{name:/previously on/i});
    await waitFor(()=>expect(getSpoilerSafeRecap).toHaveBeenCalled());
    expect(screen.queryByText(/UNVERIFIED_FUTURE_TITLE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/up to chapter/i)).not.toBeInTheDocument();
  });

  it("stays hidden when the reader was active recently", () => {
    const recent = new Date(Date.now() - DAY).toISOString();
    render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: recent }} chapter={chapter} />);
    expect(screen.queryByRole("heading", { name: /previously on/i })).not.toBeInTheDocument();
    expect(getSpoilerSafeRecap).not.toHaveBeenCalled();
  });

  it("does not show again for the same return after dismissal", async () => {
    const { unmount } = render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: longAgo }} chapter={chapter} />);
    await screen.findByRole("heading", { name: /previously on/i });
    fireEvent.click(screen.getByRole("button", { name: /close recap/i }));
    unmount();
    render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: longAgo }} chapter={chapter} />);
    expect(screen.queryByRole("heading", { name: /previously on/i })).not.toBeInTheDocument();
  });

  it("'Hide recaps' turns the setting off and dismisses the card", async () => {
    render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: longAgo }} chapter={chapter} />);
    await screen.findByRole("heading", { name: /previously on/i });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /hide recaps/i }));
    });
    await waitFor(() => expect(screen.queryByRole("heading", { name: /previously on/i })).not.toBeInTheDocument());
    expect(window.localStorage.getItem(RECAP_DAYS_KEY)).toBe("0");
  });

  it("does nothing when the setting is off", () => {
    window.localStorage.setItem(RECAP_DAYS_KEY, "0");
    render(<PreviouslyOn novelId={1} progress={{ chapter_number: 4, percent: 50, updated_at: longAgo }} chapter={chapter} />);
    expect(screen.queryByRole("heading", { name: /previously on/i })).not.toBeInTheDocument();
  });
});
