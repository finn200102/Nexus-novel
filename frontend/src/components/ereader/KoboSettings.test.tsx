import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KoboSettings from "./KoboSettings";
import { koboEndpointLine, koboService } from "../../services/koboService";
import { organizationService } from "../../services/organizationService";

vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast: vi.fn() }) }));
vi.mock("../../services/organizationService", () => ({ organizationService: { listShelves: vi.fn() } }));
vi.mock("../../services/koboService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/koboService")>();
  return { ...actual, koboService: { list: vi.fn(), create: vi.fn(), setShelf: vi.fn(), revoke: vi.fn() } };
});

describe("Kobo settings", () => {
  beforeEach(() => {
    vi.mocked(koboService.list).mockReset().mockResolvedValue({ kepub: false, devices: [] });
    vi.mocked(organizationService.listShelves).mockReset().mockResolvedValue([
      { id: 4, name: "Commute", position: 0, novel_ids: [] },
    ]);
  });

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
