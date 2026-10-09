import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AddStorySheet } from "./AddStorySheet";
import { parseLinks, STORY_ADDED } from "./addStoryEvents";
import { novelService } from "../../services/novelService";
import { renderWithToasts } from "../organization/testUtils";

vi.mock("../../context/useLibraryContext", () => ({
  useLibraryContext: () => ({
    activeLibraryId: 1,
    libraries: [{ id: 1, name: "Main" }, { id: 2, name: "Shared" }],
  }),
}));
vi.mock("../../services/novelService", () => ({ novelService: { addNovel: vi.fn(), addNovels: vi.fn() } }));
vi.mock("../../services/liveSearchService", () => ({ liveSearchService: { jobs: vi.fn().mockResolvedValue([]) } }));

describe("parseLinks", () => {
  it("splits on lines, commas and spaces and drops duplicates", () => {
    expect(parseLinks(" https://a\nhttps://b, https://a  ")).toEqual(["https://a", "https://b"]);
  });
});

describe("AddStorySheet", () => {
  beforeEach(() => vi.clearAllMocks());

  it("prefills the link and library and adds one story", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const added = vi.fn();
    window.addEventListener(STORY_ADDED, added);
    vi.mocked(novelService.addNovel).mockResolvedValue({});
    renderWithToasts(<AddStorySheet open onClose={onClose} request={{ url: "https://x/1", libraryId: 2 }} />);

    expect(screen.getByLabelText("Story link")).toHaveValue("https://x/1");
    expect(screen.getByLabelText("Add to library")).toHaveValue("2");
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    await waitFor(() => expect(novelService.addNovel).toHaveBeenCalledWith(2, "https://x/1"));
    expect(onClose).toHaveBeenCalled();
    expect(added).toHaveBeenCalled();
    window.removeEventListener(STORY_ADDED, added);
  });

  it("adds several links at once and explains an empty field", async () => {
    const user = userEvent.setup();
    vi.mocked(novelService.addNovels).mockResolvedValue([]);
    renderWithToasts(<AddStorySheet open onClose={vi.fn()} request={{}} />);

    await user.click(screen.getByRole("button", { name: "Add to library" }));
    expect(screen.getByText("Paste a link to a story.")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Story link"), "https://a{enter}https://b");
    await user.click(screen.getByRole("button", { name: "Add to library" }));
    await waitFor(() => expect(novelService.addNovels).toHaveBeenCalledWith(1, ["https://a", "https://b"]));
  });
});
