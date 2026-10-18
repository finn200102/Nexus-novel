import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KoboSettings from "./KoboSettings";
import { koboEndpointLine, koboService } from "../../services/koboService";
import { activateAccountStorage } from "../../services/accountStorage";
import { organizationService } from "../../services/organizationService";

vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast: vi.fn() }) }));
vi.mock("../../services/organizationService", () => ({ organizationService: { listShelves: vi.fn() } }));
vi.mock("../../services/koboService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/koboService")>();
  return { ...actual, koboService: { list: vi.fn(), create: vi.fn(), setShelf: vi.fn(), revoke: vi.fn(), books: vi.fn(), confirmVersion: vi.fn() } };
});

beforeEach(() => {
    vi.mocked(koboService.list).mockReset().mockResolvedValue({ kepub: false, devices: [] });
    vi.mocked(koboService.books).mockReset().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    vi.mocked(koboService.confirmVersion).mockReset().mockResolvedValue({ confirmed: true, fingerprint: 'a'.repeat(64) });
    vi.mocked(organizationService.listShelves).mockReset().mockResolvedValue([
      { id: 4, name: "Commute", position: 0, novel_ids: [] },
    ]);
  });

describe("Kobo settings", () => {
  it("builds the eReader.conf line from the API path", () => {
    expect(koboEndpointLine("/kobo/abc", "http://nexus.lan:8180")).toBe("api_endpoint=http://nexus.lan:8180/api/kobo/abc");
  });

  it("marks the feature experimental, explains EPUB fallback and shows the line once", async () => {
    vi.mocked(koboService.create).mockResolvedValue({
      id: 1, label: "Clara", shelf_id: 9, shelf_name: "Kobo", created_at: null, last_used_at: null, last_sync_at: null,
      token: "tok", endpoint_path: "/kobo/tok",
    });
    render(<KoboSettings />);
    expect(await screen.findByText(/kepubify is missing/)).toBeInTheDocument();
    expect(screen.getByText("Experimental:")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Kobo (new shelf)" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Device name"), { target: { value: "Clara" } });
    fireEvent.click(screen.getByRole("button", { name: /Set up Kobo/ }));
    expect(await screen.findByText(`api_endpoint=${window.location.origin}/api/kobo/tok`)).toBeInTheDocument();
    expect(koboService.create).toHaveBeenCalledWith("Clara", null);
  });
});


it("requires reviewed installed version and posts the exact account-owned snapshot", async () => {
  vi.mocked(koboService.list).mockResolvedValue({ kepub: true, devices: [{ id: 9, label: "Clara", shelf_id: 4, shelf_name: "Commute", created_at: null, last_used_at: null, last_sync_at: null }] });
  const book = { entitlement_id: "owned-book", novel_id: 7, title: "Known story", fingerprint: "a".repeat(64), generated_at: "2026-10-16T10:00:00Z", chapter_count: 3, manifest_epoch: "12345678-1234-1234-1234-123456789abc", manifest_revision: "17", reading_run_key: null, confirmed: false, review_reason: "book_version_confirmation_required", identity_known: true };
  vi.mocked(koboService.books).mockResolvedValue({ items: [book], total: 1, offset: 0, limit: 50 });
  render(<KoboSettings />);
  fireEvent.click(await screen.findByRole("button", { name: "Review installed book versions" }));
  expect(await screen.findByText("Known story")).toBeInTheDocument();
  const confirm = screen.getByRole("button", { name: "Confirm installed version" });
  expect(confirm).toBeDisabled(); expect(koboService.confirmVersion).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox", { name: /I checked that this generated version/ }));
  fireEvent.click(confirm);
  await waitFor(() => expect(koboService.confirmVersion).toHaveBeenCalledWith(9, "owned-book", { expected_fingerprint: book.fingerprint, expected_manifest_epoch: book.manifest_epoch, expected_manifest_revision: "17", reading_run_key: null }));
});


it("does not show a late previous-account book list after switching accounts", async () => {
  const device = { id: 9, label: "Clara", shelf_id: 4, shelf_name: "Commute", created_at: null, last_used_at: null, last_sync_at: null };
  let resolve!: (value: Awaited<ReturnType<typeof koboService.books>>) => void;
  vi.mocked(koboService.list).mockResolvedValue({ kepub: true, devices: [device] });
  vi.mocked(koboService.books).mockReturnValue(new Promise((done) => { resolve = done; }));
  render(<KoboSettings />);
  fireEvent.click(await screen.findByRole("button", { name: "Review installed book versions" }));
  vi.mocked(koboService.list).mockResolvedValue({ kepub: true, devices: [] });
  act(() => activateAccountStorage("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"));
  await waitFor(() => expect(screen.queryByText("Clara")).not.toBeInTheDocument());
  await act(async () => resolve({ items: [{ entitlement_id: "old", novel_id: 7, title: "Private previous-account book", fingerprint: "a".repeat(64), generated_at: null, chapter_count: 3, manifest_epoch: "12345678-1234-1234-1234-123456789abc", manifest_revision: "1", reading_run_key: null, confirmed: false, review_reason: null, identity_known: true }], total: 1, offset: 0, limit: 50 }));
  expect(screen.queryByText("Private previous-account book")).not.toBeInTheDocument();
});
