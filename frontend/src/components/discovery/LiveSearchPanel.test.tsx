import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LiveSearchPanel from "./LiveSearchPanel";
import { liveSearchService } from "../../services/liveSearchService";

vi.mock("../../services/liveSearchService", async () => {
  const actual = await vi.importActual<typeof import("../../services/liveSearchService")>("../../services/liveSearchService");
  return { ...actual, liveSearchService: { search: vi.fn(), browse: vi.fn() } };
});

describe("LiveSearchPanel", () => {
  it("searches the chosen sites, lists merged hits and per-site errors, and adds a hit", async () => {
    vi.mocked(liveSearchService.search).mockResolvedValue({
      page: 1,
      results: [{
        id: 5, metadata_id: 5, title: "Mother of Learning", author: "nobody103", source_url: "https://www.royalroad.com/fiction/21220",
        site: "royalroad", description: null, img_url: null, word_count: 1000, chapter_count: 108, status: null, sources: ["live", "local"],
      }],
      errors: [{ site: "fanfiction", code: "rate_limited", message: "HTTP 429" }],
    });
    const onAdd = vi.fn().mockResolvedValue(undefined);
    render(<LiveSearchPanel onAdd={onAdd} />);

    fireEvent.click(screen.getByRole("button", { name: "AO3" }));
    fireEvent.change(screen.getByLabelText("Search the source sites"), { target: { value: "mother" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("Mother of Learning")).toBeTruthy();
    expect(liveSearchService.search).toHaveBeenCalledWith("mother", ["royalroad", "fanfiction"], 1);
    expect(screen.getByText("FanFiction.net: rate limited, try again later")).toBeTruthy();
    expect(screen.getByText(/in catalog/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Add/ }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ source_url: "https://www.royalroad.com/fiction/21220" }));
  });
});
