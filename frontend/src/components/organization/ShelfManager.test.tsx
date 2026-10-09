import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ShelfManager } from "./ShelfManager";
import { organizationService } from "../../services/organizationService";
import { renderWithToasts } from "./testUtils";

vi.mock("../../services/organizationService", () => ({
  organizationService: {
    createShelf: vi.fn(),
    renameShelf: vi.fn(),
    deleteShelf: vi.fn(),
  },
}));

const shelves = [
  { id: 1, name: "Favourites", position: 1, novel_ids: [10, 11] },
  { id: 2, name: "To read", position: 2, novel_ids: [] },
];

const renderManager = (overrides: Partial<React.ComponentProps<typeof ShelfManager>> = {}) =>
  renderWithToasts(
    <ShelfManager open onClose={vi.fn()} shelves={shelves} activeShelfId={null} onSelect={vi.fn()} onChanged={vi.fn()} {...overrides} />,
  );

describe("ShelfManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a shelf and selects it", async () => {
    const onSelect = vi.fn();
    const onChanged = vi.fn();
    vi.mocked(organizationService.createShelf).mockResolvedValue({ id: 3, name: "Rereads", position: 3, novel_ids: [] });
    renderManager({ onSelect, onChanged });

    fireEvent.change(screen.getByLabelText("New shelf"), { target: { value: "Rereads" } });
    fireEvent.click(screen.getByRole("button", { name: "Create shelf" }));

    await waitFor(() => expect(organizationService.createShelf).toHaveBeenCalledWith("Rereads"));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(3));
    expect(onChanged).toHaveBeenCalledWith([...shelves, expect.objectContaining({ name: "Rereads" })]);
  });

  it("renames a shelf", async () => {
    const onChanged = vi.fn();
    vi.mocked(organizationService.renameShelf).mockResolvedValue({ ...shelves[1], name: "Later" });
    renderManager({ onChanged });

    fireEvent.click(screen.getByRole("button", { name: "Rename To read" }));
    fireEvent.change(screen.getByLabelText("New name for To read"), { target: { value: "Later" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(organizationService.renameShelf).toHaveBeenCalledWith(2, "Later"));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith([shelves[0], expect.objectContaining({ name: "Later" })]));
  });

  it("deletes only after confirming", async () => {
    vi.mocked(organizationService.deleteShelf).mockResolvedValue(undefined);
    const onChanged = vi.fn();
    renderManager({ onChanged });

    fireEvent.click(screen.getByRole("button", { name: "Delete To read" }));
    expect(organizationService.deleteShelf).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(organizationService.deleteShelf).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete To read" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(organizationService.deleteShelf).toHaveBeenCalledWith(2));
    expect(onChanged).toHaveBeenCalledWith([shelves[0]]);
  });
});
