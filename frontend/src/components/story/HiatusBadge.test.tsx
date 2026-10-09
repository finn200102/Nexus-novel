import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import apiClient from "../../services/apiClient";
import HiatusBadge from "./HiatusBadge";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn() },
}));

const get = vi.mocked(apiClient.get);

describe("HiatusBadge", () => {
  beforeEach(() => get.mockReset());

  it("shows the label with a warning tone on hiatus", async () => {
    get.mockResolvedValue({
      data: { metadata_id: 3, hiatus: { state: "hiatus", last_update_at: "2025-08-01T00:00:00Z", label: "No update in 14 months" } },
    } as never);
    render(<HiatusBadge metadataId={3} />);

    const badge = await screen.findByText("No update in 14 months");
    expect(get).toHaveBeenCalledWith("/stories/3");
    expect(badge.className).toContain("ui-badge--warning");
  });

  it("uses a muted tone while the story is active", async () => {
    get.mockResolvedValue({
      data: { metadata_id: 3, hiatus: { state: "active", last_update_at: null, label: "Updated 3 days ago" } },
    } as never);
    render(<HiatusBadge metadataId={3} />);

    const badge = await screen.findByText("Updated 3 days ago");
    expect(badge.className).toContain("ui-badge--neutral");
  });

  it("renders nothing when the request fails", async () => {
    get.mockRejectedValueOnce(new Error("offline"));
    const { container } = render(<HiatusBadge metadataId={3} />);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
