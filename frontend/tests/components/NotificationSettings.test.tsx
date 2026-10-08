import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NotificationSettings from "../../src/components/notifications/NotificationSettings";
import { ToastProvider } from "../../src/context/ToastContext";
import { notificationService } from "../../src/services/notificationService";

vi.mock("../../src/services/notificationService", () => ({
  notificationService: {
    vapidPublicKey: vi.fn(),
    devices: vi.fn(),
    subscribePush: vi.fn(),
    unsubscribePush: vi.fn(),
    removeDevice: vi.fn(),
    channels: vi.fn(),
    addChannel: vi.fn(),
    updateChannel: vi.fn(),
    removeChannel: vi.fn(),
    sendTest: vi.fn(),
  },
}));

const mocked = vi.mocked(notificationService);

const channel = {
  id: 7,
  kind: "apprise",
  label: "Phone",
  url_hint: "ntfy://ntfy.sh/...",
  enabled: true,
  last_error: null,
  created_at: null,
};

const renderSettings = () =>
  render(
    <ToastProvider>
      <NotificationSettings />
    </ToastProvider>
  );

describe("NotificationSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.devices.mockResolvedValue([]);
    mocked.channels.mockResolvedValue([channel]);
  });

  it("shows channels by scheme and host only", async () => {
    renderSettings();

    expect(await screen.findByText("Phone")).toBeInTheDocument();
    expect(screen.getByText(/ntfy:\/\/ntfy\.sh\/\.\.\./)).toBeInTheDocument();
    expect(screen.queryByText(/topic-secret/)).not.toBeInTheDocument();
  });

  it("links to the Apprise URL format help", async () => {
    renderSettings();

    const link = await screen.findByRole("link", { name: /how to write apprise urls/i });
    expect(link).toHaveAttribute("href", "https://github.com/caronc/apprise/wiki");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("saves a new Apprise URL with its label", async () => {
    mocked.addChannel.mockResolvedValue({ ...channel, id: 8, label: "Desk" });
    const user = userEvent.setup();
    renderSettings();
    await screen.findByText("Phone");

    await user.type(screen.getByLabelText(/label \(optional\)/i), "Desk");
    await user.type(screen.getByLabelText(/apprise url/i), "json://localhost:9/");
    await user.click(screen.getByRole("button", { name: /save url/i }));

    await waitFor(() =>
      expect(mocked.addChannel).toHaveBeenCalledWith({ url: "json://localhost:9/", label: "Desk" })
    );
  });

  it("shows a result line for each channel after a test", async () => {
    mocked.sendTest.mockResolvedValue({
      channels: [{ id: 7, label: "Phone", url_hint: "ntfy://ntfy.sh/...", ok: false, error: "Delivery failed" }],
      push: { sent: 0, failed: 0, removed: 0 },
    });
    const user = userEvent.setup();
    renderSettings();
    await screen.findByText("Phone");

    await user.click(screen.getByRole("button", { name: /send test/i }));

    const results = await screen.findByRole("list", { name: /test results/i });
    expect(results).toHaveTextContent("Phone: failed (Delivery failed)");
  });

  it("explains when the browser has no push support", async () => {
    renderSettings();

    expect(await screen.findByText(/does not support push notifications/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /turn on push notifications/i })).not.toBeInTheDocument();
  });
});
