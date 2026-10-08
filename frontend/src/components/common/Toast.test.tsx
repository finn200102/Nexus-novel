import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../context/ToastContext";
import { useToast } from "../../context/useToast";
import { ToastContainer } from "./Toast";

let api: ReturnType<typeof useToast>;
function Grab() {
  api = useToast();
  return null;
}
const setup = () =>
  render(
    <ToastProvider>
      <Grab />
      <ToastContainer />
    </ToastProvider>,
  );

describe("ToastContainer", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("puts messages in a polite status region and errors in an alert region", () => {
    setup();
    act(() => {
      api.addToast("Saved", "success");
      api.addToast("Download failed", "error");
    });
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("alert")).toHaveTextContent("Download failed");
  });

  it("auto-dismisses after 5 s but errors stay", () => {
    setup();
    act(() => {
      api.addToast("Saved", "success");
      api.addToast("Download failed", "error");
    });
    act(() => vi.advanceTimersByTime(5100));
    expect(screen.queryByText("Saved")).toBeNull();
    expect(screen.getByText("Download failed")).toBeInTheDocument();
  });

  it("pauses while hovered", async () => {
    setup();
    act(() => api.addToast("Saved", "success"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.hover(screen.getByText("Saved"));
    act(() => vi.advanceTimersByTime(8000));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    await user.unhover(screen.getByText("Saved"));
    act(() => vi.advanceTimersByTime(5100));
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("shows at most three and runs actions", async () => {
    setup();
    const undo = vi.fn();
    act(() => {
      api.addToast("One", "info", 0, { action: { label: "Undo", onClick: undo } });
      api.addToast("Two", "info", 0);
      api.addToast("Three", "info", 0);
      api.addToast("Four", "info", 0);
    });
    expect(screen.queryByText("Four")).toBeNull();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(undo).toHaveBeenCalled();
    expect(screen.getByText("Four")).toBeInTheDocument();
  });
});
