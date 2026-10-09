import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FollowAuthorButton from "./FollowAuthorButton";
import NewWorksSection from "./NewWorksSection";
import { followService } from "../../services/followService";

const addToast = vi.fn();
vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast }) }));
vi.mock("../../services/followService", () => ({
  followService: {
    author: vi.fn(),
    follow: vi.fn(),
    unfollow: vi.fn(),
    newWorks: vi.fn(),
    markNewWorksRead: vi.fn(),
  },
}));

const profile = (overrides = {}) => ({
  id: 4, site: "royalroad", name: "nobody103", key: "100374", followable: true,
  follow_id: null as number | null, last_checked_at: null, works: [], ...overrides,
});

describe("FollowAuthorButton", () => {
  beforeEach(() => vi.clearAllMocks());

  it("follows the story's author on its site and flips to Following", async () => {
    vi.mocked(followService.author).mockResolvedValue({ id: 4, name: "nobody103", site: "royalroad", profiles: [profile()] });
    vi.mocked(followService.follow).mockResolvedValue({
      id: 9, kind: "author", site: "royalroad", key: "100374", name: "nobody103",
      metadata_author_id: 4, metadata_target_id: 1, created_at: null,
    });
    render(<FollowAuthorButton authorId={4} />);

    fireEvent.click(await screen.findByRole("button", { name: "Follow author" }));
    await screen.findByRole("button", { name: "Following" });
    expect(followService.follow).toHaveBeenCalledWith({
      kind: "author", site: "royalroad", key: "100374", name: "nobody103", metadata_author_id: 4,
    });
    expect(screen.getByRole("button", { name: "Following" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Following" }));
    await screen.findByRole("button", { name: "Follow author" });
    expect(followService.unfollow).toHaveBeenCalledWith(9);
  });

  it("stays hidden when the site has no author pages", async () => {
    vi.mocked(followService.author).mockResolvedValue({
      id: 4, name: "x", site: "webnovel", profiles: [profile({ site: "webnovel", followable: false })],
    });
    const { container } = render(<FollowAuthorButton authorId={4} />);
    await waitFor(() => expect(followService.author).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("NewWorksSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists new works with who they come from and marks them seen", async () => {
    vi.mocked(followService.newWorks).mockResolvedValueOnce([
      {
        id: 3, event_type: "author_new_work", message: "New work by nobody103: Zenith", created_at: "2026-10-09T10:00:00",
        read_at: null, title: "Zenith of Sorcery", url: "https://www.royalroad.com/fiction/71045", site: "royalroad",
        metadata_id: 71, author: "nobody103", follow: { id: 1, kind: "author", name: "nobody103" },
      },
    ]).mockResolvedValue([]);
    vi.mocked(followService.markNewWorksRead).mockResolvedValue();
    render(<MemoryRouter><NewWorksSection /></MemoryRouter>);

    expect(await screen.findByRole("link", { name: "Zenith of Sorcery" })).toHaveAttribute("href", "/story/71");
    expect(screen.getByText(/By nobody103/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark Zenith of Sorcery seen" }));
    await waitFor(() => expect(followService.markNewWorksRead).toHaveBeenCalledWith([3]));
    await waitFor(() => expect(screen.queryByText("Zenith of Sorcery")).not.toBeInTheDocument());
  });
});
