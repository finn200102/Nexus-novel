import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HideButton, UNDO_WINDOW_MS } from "./HideButton";
import { organizationService } from "../../services/organizationService";
import { renderWithToasts } from "./testUtils";

vi.mock("../../services/organizationService", () => ({
  organizationService: {
    addBlocklistEntry: vi.fn(),
    removeBlocklistEntry: vi.fn(),
  },
}));

const created = { id: 42, kind: "tag" as const, value: "gore", created_at: null };

describe("HideButton", () => {
  beforeEach(() => {
    vi.mocked(organizationService.addBlocklistEntry).mockResolvedValue(created);
    vi.mocked(organizationService.removeBlocklistEntry).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("hides the value with one click and reports a success toast", async () => {
    const onChange = vi.fn();
    const { addToast } = renderWithToasts(<HideButton kind="tag" value="gore" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Hide tag gore" }));

    await waitFor(() => expect(organizationService.addBlocklistEntry).toHaveBeenCalledWith("tag", "gore"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(created));
    expect(addToast).toHaveBeenCalledWith(expect.stringContaining('"gore"'), "success");
  });

  it("offers undo, which removes the entry again", async () => {
    const onChange = vi.fn();
    renderWithToasts(<HideButton kind="tag" value="gore" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Hide tag gore" }));

    const undo = await screen.findByRole("button", { name: /Undo/ });
    fireEvent.click(undo);

    await waitFor(() => expect(organizationService.removeBlocklistEntry).toHaveBeenCalledWith(42));
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(null));
    expect(screen.getByRole("button", { name: "Hide tag gore" })).toBeTruthy();
  });

  it("stops offering undo after the undo window", async () => {
    vi.useFakeTimers();
    renderWithToasts(<HideButton kind="author" value="Alice" />);
    fireEvent.click(screen.getByRole("button", { name: "Hide author Alice" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: /Undo/ })).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(UNDO_WINDOW_MS + 1);
    });

    expect(screen.queryByRole("button", { name: /Undo/ })).toBeNull();
  });

  it("reports a failed hide through a toast and keeps the button", async () => {
    vi.mocked(organizationService.addBlocklistEntry).mockRejectedValue(new Error("network"));
    const { addToast } = renderWithToasts(<HideButton kind="genre" value="Horror" />);

    fireEvent.click(screen.getByRole("button", { name: "Hide genre Horror" }));

    await waitFor(() => expect(addToast).toHaveBeenCalledWith(expect.any(String), "error"));
    expect((screen.getByRole("button", { name: "Hide genre Horror" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
