import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HiddenContentPanel from "./HiddenContentPanel";
import { organizationService } from "../../services/organizationService";
import { renderWithToasts } from "./testUtils";

vi.mock("../../services/organizationService", () => ({
  organizationService: {
    listBlocklist: vi.fn(),
    addBlocklistEntry: vi.fn(),
    removeBlocklistEntry: vi.fn(),
  },
}));

const existing = [
  { id: 1, kind: "tag" as const, value: "gore", created_at: null },
  { id: 2, kind: "author" as const, value: "Alice", created_at: null },
];

describe("HiddenContentPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(organizationService.listBlocklist).mockResolvedValue(existing);
  });

  it("lists entries grouped by kind", async () => {
    renderWithToasts(<HiddenContentPanel />);

    expect(await screen.findByText("gore")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Tags" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Authors" })).toBeTruthy();
  });

  it("adds a value of the chosen kind and clears the field", async () => {
    vi.mocked(organizationService.addBlocklistEntry).mockResolvedValue({ id: 3, kind: "fandom", value: "Naruto", created_at: null });
    renderWithToasts(<HiddenContentPanel />);
    await screen.findByText("gore");

    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "fandom" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "  Naruto " } });
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));

    await waitFor(() => expect(organizationService.addBlocklistEntry).toHaveBeenCalledWith("fandom", "Naruto"));
    expect(await screen.findByText("Naruto")).toBeTruthy();
    expect((screen.getByLabelText("Value") as HTMLInputElement).value).toBe("");
  });

  it("shows an entry again", async () => {
    vi.mocked(organizationService.removeBlocklistEntry).mockResolvedValue(undefined);
    renderWithToasts(<HiddenContentPanel />);
    await screen.findByText("gore");

    fireEvent.click(screen.getByRole("button", { name: "Show gore again" }));

    await waitFor(() => expect(organizationService.removeBlocklistEntry).toHaveBeenCalledWith(1));
    await waitFor(() => expect(screen.queryByText("gore")).toBeNull());
  });

  it("keeps the Hide button disabled until a value is typed", async () => {
    renderWithToasts(<HiddenContentPanel />);
    await screen.findByText("gore");
    const form = screen.getByLabelText("Value").closest("form") as HTMLFormElement;

    expect((within(form).getByRole("button", { name: "Hide" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
