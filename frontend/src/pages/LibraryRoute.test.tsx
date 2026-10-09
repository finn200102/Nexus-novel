import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OPEN_ADD_STORY } from "../components/add/addStoryEvents";
import LibraryRoute from "./LibraryRoute";

const library = { activeLibraryId: null as number | null, isLoading: true, selectLibrary: vi.fn() };
vi.mock("../context/useLibraryContext", () => ({ useLibraryContext: () => library }));
vi.mock("./Library", () => ({ default: () => <p>library page</p> }));
vi.mock("../components/household/SharedWithMe", () => ({ SharedWithMe: () => null }));

describe("LibraryRoute ?add=1", () => {
  beforeEach(() => {
    library.activeLibraryId = null;
    library.isLoading = true;
  });

  it("opens the Add story sheet once the libraries have loaded", () => {
    const opened = vi.fn();
    window.addEventListener(OPEN_ADD_STORY, opened);
    const tree = () => (
      <MemoryRouter initialEntries={["/library?add=1"]}>
        <Routes>
          <Route path="/library" element={<LibraryRoute />} />
        </Routes>
      </MemoryRouter>
    );
    const { rerender } = render(tree());
    expect(opened).not.toHaveBeenCalled();

    library.activeLibraryId = 7;
    library.isLoading = false;
    rerender(tree());
    expect(opened).toHaveBeenCalledTimes(1);
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toMatchObject({ libraryId: 7 });
    window.removeEventListener(OPEN_ADD_STORY, opened);
  });
});
