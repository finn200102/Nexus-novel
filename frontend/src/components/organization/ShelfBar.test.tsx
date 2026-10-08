import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ShelfBar } from "./ShelfBar";
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

describe("ShelfBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("filters by shelf and returns to all shelves", () => {
    const onSelect = vi.fn();
    renderWithToasts(<ShelfBar shelves={shelves} activeShelfId={null} onSelect={onSelect} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /^Favourites/ }));
    expect(onSelect).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "All shelves" }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("creates a shelf and selects it", async () => {
    const onSelect = vi.fn();
    const onChanged = vi.fn();
    vi.mocked(organizationService.createShelf).mockResolvedValue({ id: 3, name: "Rereads", position: 3, novel_ids: [] });
    renderWithToasts(<ShelfBar shelves={shelves} activeShelfId={null} onSelect={onSelect} onChanged={onChanged} />);

    fireEvent.change(screen.getByLabelText("New shelf name"), { target: { value: "Rereads" } });
    fireEvent.click(screen.getByRole("button", { name: "Create shelf" }));

    await waitFor(() => expect(organizationService.createShelf).toHaveBeenCalledWith("Rereads"));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(3));
    expect(onChanged).toHaveBeenCalledWith([...shelves, expect.objectContaining({ name: "Rereads" })]);
  });

  it("renames a shelf inline", async () => {
    const onChanged = vi.fn();
    vi.mocked(organizationService.renameShelf).mockResolvedValue({ ...shelves[1], name: "Later" });
    renderWithToasts(<ShelfBar shelves={shelves} activeShelfId={null} onSelect={vi.fn()} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Rename To read" }));
    fireEvent.change(screen.getByLabelText("New name for To read"), { target: { value: "Later" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(organizationService.renameShelf).toHaveBeenCalledWith(2, "Later"));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith([shelves[0], expect.objectContaining({ name: "Later" })]));
  });

  it("deletes only after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.mocked(organizationService.deleteShelf).mockResolvedValue(undefined);
    const onChanged = vi.fn();
    renderWithToasts(<ShelfBar shelves={shelves} activeShelfId={null} onSelect={vi.fn()} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete To read" }));
    expect(organizationService.deleteShelf).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete To read" }));
    await waitFor(() => expect(organizationService.deleteShelf).toHaveBeenCalledWith(2));
    expect(onChanged).toHaveBeenCalledWith([shelves[0]]);
  });
});
