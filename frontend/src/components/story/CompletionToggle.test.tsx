import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import apiClient from "../../services/apiClient";
import CompletionToggle from "./CompletionToggle";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), put: vi.fn() },
  getUserFacingError: (_err: unknown, fallback: string) => fallback,
}));

const get = vi.mocked(apiClient.get);
const put = vi.mocked(apiClient.put);

describe("CompletionToggle", () => {
  beforeEach(() => {
    get.mockReset();
    put.mockReset();
  });

  it("reflects the saved preference", async () => {
    get.mockResolvedValue({ data: { notify_when_complete: true } } as never);
    render(<CompletionToggle novelId={7} />);

    const toggle = await screen.findByRole("switch", { name: "Tell me when it's finished" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(get).toHaveBeenCalledWith("/personal/novels/7");
  });

  it("saves the new value with a PUT when toggled", async () => {
    get.mockResolvedValue({ data: { notify_when_complete: false } } as never);
    put.mockResolvedValue({ data: {} } as never);
    render(<CompletionToggle novelId={7} />);

    const toggle = await screen.findByRole("switch", { name: "Tell me when it's finished" });
    await waitFor(() => expect(toggle).toBeEnabled());
    await userEvent.click(toggle);

    expect(put).toHaveBeenCalledWith("/personal/novels/7", { notify_when_complete: true });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("reverts and shows an error when saving fails", async () => {
    get.mockResolvedValue({ data: { notify_when_complete: false } } as never);
    put.mockRejectedValue(new Error("boom"));
    render(<CompletionToggle novelId={7} />);

    const toggle = await screen.findByRole("switch", { name: "Tell me when it's finished" });
    await waitFor(() => expect(toggle).toBeEnabled());
    await userEvent.click(toggle);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save this setting.");
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });
});
