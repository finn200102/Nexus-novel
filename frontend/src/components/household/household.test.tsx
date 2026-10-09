import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithToasts } from "../organization/testUtils";
import { householdService } from "../../services/householdService";
import { resetContentLimitsCache } from "../../hooks/useContentLimits";
import { ShareShelfDialog } from "./ShareShelfDialog";
import { SharedWithMe } from "./SharedWithMe";
import { ContentLimitsDialog } from "./ContentLimitsDialog";
import { LimitedProfileNotice } from "./LimitedProfileNotice";

vi.mock("../../context/AuthContext", () => ({ useAuth: () => ({ user: { id: 7, username: "kid" } }) }));
vi.mock("../../services/householdService", () => ({
  householdService: {
    shareTargets: vi.fn(),
    shares: vi.fn(),
    share: vi.fn(),
    unshare: vi.fn(),
    setShareNotes: vi.fn(),
    sharedWithMe: vi.fn(),
    shelfStories: vi.fn(),
    removeEntry: vi.fn(),
    myLimits: vi.fn(),
    setLimits: vi.fn(),
  },
}));

const service = vi.mocked(householdService);

beforeEach(() => {
  vi.clearAllMocks();
  resetContentLimitsCache();
});

describe("ShareShelfDialog", () => {
  it("shares a shelf with a picked person and permission", async () => {
    service.shareTargets.mockResolvedValue([{ id: 7, username: "kid" }]);
    service.shares.mockResolvedValue({ shelf_id: 3, share_notes: false, shares: [] });
    service.share.mockResolvedValue({ shelf_id: 3, share_notes: false, shares: [{ user_id: 7, username: "kid", permission: "collaborate" }] });
    const onChanged = vi.fn();
    renderWithToasts(<ShareShelfDialog shelf={{ id: 3, name: "Family" }} onClose={vi.fn()} onChanged={onChanged} />);

    expect(await screen.findByText("Not shared with anyone yet.")).toBeInTheDocument();
    expect(screen.getByText(/downloaded chapters, EPUBs and audio stay yours/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Person"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("radio", { name: "Can add stories" }));
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    await waitFor(() => expect(service.share).toHaveBeenCalledWith(3, 7, "collaborate"));
    expect(await screen.findByRole("button", { name: "Stop sharing with kid" })).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledWith(3, 1);
  });
});

describe("SharedWithMe", () => {
  it("lists shared shelves and their stories as catalog links", async () => {
    service.sharedWithMe.mockResolvedValue([
      { id: 3, name: "Family", owner: { id: 1, username: "parent" }, permission: "view", share_notes: true, story_count: 1 },
    ]);
    service.shelfStories.mockResolvedValue({
      id: 3, name: "Family", owner: { id: 1, username: "parent" }, permission: "view", share_notes: true,
      stories: [{ entry_id: 5, metadata_id: 42, title: "Gentle", author: "Ann", cover_url: null, site: "royalroad",
        source_url: "https://example/42", added_by: "parent", added_by_me: false, notes: "Read together", in_my_library: false }],
    });
    renderWithToasts(<MemoryRouter><SharedWithMe /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Family" }));
    const link = await screen.findByRole("link", { name: /Gentle/ });
    expect(link).toHaveAttribute("href", "/story/42");
    expect(screen.getByText(/Read together/)).toBeInTheDocument();
    service.unshare.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Leave Family" }));
    await waitFor(() => expect(service.unshare).toHaveBeenCalledWith(3, 7));
    await waitFor(() => expect(screen.queryByText("Shared with me")).not.toBeInTheDocument());
  });

  it("renders nothing without shared shelves", async () => {
    service.sharedWithMe.mockResolvedValue([]);
    const { container } = renderWithToasts(<MemoryRouter><SharedWithMe /></MemoryRouter>);
    await waitFor(() => expect(service.sharedWithMe).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("content limits", () => {
  it("lets an admin set a maximum rating and blocked tags", async () => {
    service.setLimits.mockResolvedValue({ content_limits: { max_content_rating: "teen", hide_unrated: true, blocked_tags: ["Gore"], limited: true } });
    const onSaved = vi.fn();
    renderWithToasts(<ContentLimitsDialog user={{ id: 9, username: "kid" }} onClose={vi.fn()} onSaved={onSaved} />);

    fireEvent.change(screen.getByLabelText("Maximum rating"), { target: { value: "teen" } });
    fireEvent.change(screen.getByLabelText("Blocked tag"), { target: { value: "Gore" } });
    fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
    fireEvent.click(screen.getByRole("button", { name: "Save limits" }));
    await waitFor(() => expect(service.setLimits).toHaveBeenCalledWith(9, { max_content_rating: "teen", hide_unrated: true, blocked_tags: ["Gore"] }));
    expect(onSaved).toHaveBeenCalledWith(9, expect.objectContaining({ limited: true }));
  });

  it("tells a limited profile about its limits", async () => {
    service.myLimits.mockResolvedValue({ max_content_rating: "teen", hide_unrated: true, blocked_tags: [], limited: true });
    renderWithToasts(<LimitedProfileNotice />);
    expect(await screen.findByText(/Limited profile: an administrator shows you stories rated up to Teen; no unrated stories/)).toBeInTheDocument();
  });
});
