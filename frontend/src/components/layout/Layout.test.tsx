import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Layout from "./Layout";
import { usePageTitle } from "../../hooks/usePageTitle";
import { ThemeProvider } from "../../theme/ThemeProvider";

const auth = { user: { username: "mira", is_admin: false } as { username: string; is_admin: boolean }, logout: vi.fn() };

vi.mock("../../context/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../context/useLibraryContext", () => ({
  useLibraryContext: () => ({ activeLibrary: { id: 1, name: "Main" }, activeLibraryId: 1, libraries: [{ id: 1, name: "Main" }] }),
}));
vi.mock("../common/SourceStatusBanner", () => ({ default: () => null }));
vi.mock("../library/CreateLibraryModal", () => ({ default: () => null }));
vi.mock("../add/AddStorySheet", () => ({
  AddStorySheet: ({ open, request }: { open: boolean; request: { libraryId?: number } }) =>
    open ? <div role="dialog" aria-label="Add story">library {request.libraryId}</div> : null,
}));
vi.mock("../../services/activityService", () => ({
  activityService: { getInbox: vi.fn().mockResolvedValue([{ novel_id: 1 }, { novel_id: 2 }]) },
}));

const Page = ({ title }: { title: string }) => {
  usePageTitle(title);
  return (
    <>
      <h1>{title}</h1>
      <Link to="/discover">Go to Discover</Link>
    </>
  );
};

const renderShell = () =>
  render(
    <ThemeProvider>
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Page title="Home" />} />
          <Route path="discover" element={<Page title="Discover" />} />
        </Route>
      </Routes>
    </MemoryRouter>
    </ThemeProvider>,
  );

describe("app shell", () => {
  beforeEach(() => {
    auth.user = { username: "mira", is_admin: false };
  });

  it("renders one main nav, a main landmark and the skip link first", async () => {
    const user = userEvent.setup();
    renderShell();
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(1);
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveFocus();
  });

  it("shows the unread count on Updates and marks the current page", async () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(await within(nav).findByText("2 stories with new chapters")).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  });

  it("shows Admin only to administrators", () => {
    const { unmount } = renderShell();
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    unmount();
    auth.user = { username: "mira", is_admin: true };
    renderShell();
    expect(screen.getByRole("link", { name: "Admin" })).toBeInTheDocument();
  });

  it("sets the document title and moves focus to the H1 after navigation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderShell();
    expect(document.title).toBe("Home – Nexus");
    await user.click(screen.getByRole("link", { name: "Go to Discover" }));
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    expect(document.title).toBe("Discover – Nexus");
    expect(screen.getByRole("heading", { level: 1, name: "Discover" })).toHaveFocus();
    expect(screen.getByTestId("route-announcer")).toHaveTextContent("Discover – Nexus");
    vi.useRealTimers();
  });

  it("opens the profile menu with settings, theme and sign out", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByRole("button", { name: /mira/ }));
    const panel = screen.getByRole("dialog", { name: "Account" });
    expect(within(panel).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings/account");
    expect(within(panel).getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Sign out" }));
    expect(auth.logout).toHaveBeenCalled();
  });

  it("opens the one Add story sheet for the active library from the top bar", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getAllByRole("button", { name: "Add story" })[0]);
    expect(screen.getByRole("dialog", { name: "Add story" })).toHaveTextContent("library 1");
  });
});
