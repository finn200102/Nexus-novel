import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalPanel } from "./PersonalPanel";
import { organizationService } from "../../services/organizationService";
import { renderWithToasts } from "./testUtils";

vi.mock("../../services/organizationService", () => ({
  organizationService: {
    getPersonal: vi.fn(),
    savePersonal: vi.fn(),
    tagSuggestions: vi.fn(),
  },
}));

describe("PersonalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(organizationService.getPersonal).mockResolvedValue({
      novel_id: 7,
      notes: "Loved **the** cast",
      rating: 3,
      user_tags: ["cozy"],
    });
    vi.mocked(organizationService.tagSuggestions).mockResolvedValue(["cozy", "slow burn"]);
    vi.mocked(organizationService.savePersonal).mockImplementation(async (_id, data) => ({
      novel_id: 7,
      notes: data.notes !== undefined ? data.notes : "Loved **the** cast",
      rating: data.rating !== undefined ? data.rating : 3,
      user_tags: data.user_tags ?? ["cozy"],
    }));
  });

  it("loads notes, rating and tags", async () => {
    renderWithToasts(<PersonalPanel novelId={7} />);

    expect(await screen.findByDisplayValue("Loved **the** cast")).toBeTruthy();
    expect(screen.getByText("3/5")).toBeTruthy();
    expect(screen.getByText("cozy")).toBeTruthy();
  });

  it("saves the rating change, and clears it when the same star is pressed again", async () => {
    renderWithToasts(<PersonalPanel novelId={7} />);
    await screen.findByDisplayValue("Loved **the** cast");

    fireEvent.click(screen.getByRole("button", { name: "Rate 5 stars" }));
    fireEvent.click(screen.getByRole("button", { name: "Save notes" }));
    await waitFor(() =>
      expect(organizationService.savePersonal).toHaveBeenLastCalledWith(7, { rating: 5 }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Rate 5 stars" }));
    expect(screen.getByText("Not rated")).toBeTruthy();
  });

  it("sends only the fields that changed", async () => {
    renderWithToasts(<PersonalPanel novelId={7} />);
    await screen.findByDisplayValue("Loved **the** cast");

    fireEvent.change(screen.getByDisplayValue("Loved **the** cast"), { target: { value: "Still loved it" } });
    fireEvent.click(screen.getByRole("button", { name: "Save notes" }));

    await waitFor(() => expect(organizationService.savePersonal).toHaveBeenCalledWith(7, { notes: "Still loved it" }));
    expect(vi.mocked(organizationService.savePersonal).mock.calls[0][1]).not.toHaveProperty("rating");
    expect(vi.mocked(organizationService.savePersonal).mock.calls[0][1]).not.toHaveProperty("user_tags");
  });

  it("renders the Markdown preview without injecting raw HTML", async () => {
    vi.mocked(organizationService.getPersonal).mockResolvedValue({
      novel_id: 7,
      notes: '<img src="x" onerror="alert(1)">**bold**',
      rating: null,
      user_tags: [],
    });
    const { container } = renderWithToasts(<PersonalPanel novelId={7} />);
    await screen.findByDisplayValue(/onerror/);

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    const preview = screen.getByLabelText("Notes preview");
    expect(preview.querySelector("img")).toBeNull();
    expect(preview.querySelector("strong")?.textContent).toBe("bold");
    expect(container.textContent).toContain('<img src="x" onerror="alert(1)">');
  });

  it("disables save until something changes", async () => {
    renderWithToasts(<PersonalPanel novelId={7} />);
    await screen.findByDisplayValue("Loved **the** cast");

    expect((screen.getByRole("button", { name: "Save notes" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
