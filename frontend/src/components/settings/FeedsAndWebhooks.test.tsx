import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FeedsAndWebhooks from "./FeedsAndWebhooks";
import { feedWebhookService } from "../../services/feedWebhookService";

const addToast = vi.fn();
vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast }) }));
vi.mock("../../services/feedWebhookService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/feedWebhookService")>();
  return {
    ...actual,
    feedWebhookService: {
      feedStatus: vi.fn(),
      rotateFeedToken: vi.fn(),
      revokeFeedToken: vi.fn(),
      listWebhooks: vi.fn(),
      createWebhook: vi.fn(),
      deleteWebhook: vi.fn(),
      testWebhook: vi.fn(),
    },
  };
});

const service = vi.mocked(feedWebhookService);

describe("FeedsAndWebhooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    service.feedStatus.mockResolvedValue({ active: false, feed_url: null });
    service.listWebhooks.mockResolvedValue([]);
  });

  it("creates a feed URL and shows it once", async () => {
    service.rotateFeedToken.mockResolvedValue({
      active: true,
      feed_url: "https://nexus.example/feeds/abc.atom",
    });
    render(<FeedsAndWebhooks />);
    fireEvent.click(await screen.findByRole("button", { name: "Create feed URL" }));
    expect(await screen.findByDisplayValue("https://nexus.example/feeds/abc.atom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Rotate feed URL" })).toBeTruthy();
  });

  it("adds a signed webhook with the chosen events", async () => {
    service.createWebhook.mockResolvedValue({
      id: 7,
      url_hint: "https://hooks.example/...",
      has_secret: true,
      event_types: ["new_chapters"],
      enabled: true,
      last_status_code: null,
      last_error: null,
      last_delivered_at: null,
      consecutive_failures: 0,
      created_at: null,
    });
    const { container } = render(<FeedsAndWebhooks />);
    await screen.findByText("No webhooks yet.");
    const urlInput = container.querySelector('input[type="url"]') as HTMLInputElement;
    const secretInput = container.querySelector('input[type="password"]') as HTMLInputElement;
    fireEvent.change(urlInput, { target: { value: "https://hooks.example/abc" } });
    fireEvent.change(secretInput, { target: { value: "shh" } });
    fireEvent.click(screen.getByRole("button", { name: "Add webhook" }));

    await waitFor(() =>
      expect(service.createWebhook).toHaveBeenCalledWith({
        url: "https://hooks.example/abc",
        secret: "shh",
        event_types: ["new_chapters"],
      }),
    );
    expect(await screen.findByText("https://hooks.example/...")).toBeTruthy();
  });

  it("reports a failed test send", async () => {
    service.listWebhooks.mockResolvedValue([
      {
        id: 3,
        url_hint: "https://hooks.example/...",
        has_secret: false,
        event_types: ["new_chapters"],
        enabled: true,
        last_status_code: 500,
        last_error: "HTTP 500",
        last_delivered_at: null,
        consecutive_failures: 1,
        created_at: null,
      },
    ]);
    service.testWebhook.mockResolvedValue({ ok: false, status_code: 500, error: "HTTP 500" });
    render(<FeedsAndWebhooks />);
    fireEvent.click(await screen.findByRole("button", { name: "Send test" }));
    await waitFor(() => expect(addToast).toHaveBeenCalledWith("Test failed: HTTP 500", "error"));
  });
});
