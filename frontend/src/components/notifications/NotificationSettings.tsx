import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { BellRing, Send, Trash2 } from "lucide-react";
import { useToast } from "../../context/useToast";
import {
  ChannelTestResult,
  NotificationChannel,
  PushDevice,
  notificationService,
} from "../../services/notificationService";
import { isPushSupported, urlBase64ToUint8Array } from "./pushSupport";
import "../../styles/integrations.css";

export const APPRISE_HELP_URL = "https://github.com/caronc/apprise/wiki";

const formatTime = (value: string | null) => (value ? new Date(value).toLocaleString() : "never");

/** The server's own message when it gave one; otherwise the fallback. */
const failureText = (error: unknown, fallback: string) => {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
  }
  return fallback;
};

const NotificationSettings: React.FC = () => {
  const { addToast } = useToast();
  const pushSupported = isPushSupported();
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(
    pushSupported ? Notification.permission : "unsupported",
  );
  const [thisDevice, setThisDevice] = useState<PushSubscription | null>(null);
  const [devices, setDevices] = useState<PushDevice[]>([]);
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [channelUrl, setChannelUrl] = useState("");
  const [channelLabel, setChannelLabel] = useState("");
  const [testResult, setTestResult] = useState<ChannelTestResult | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [deviceRows, channelRows] = await Promise.all([
        notificationService.devices(),
        notificationService.channels(),
      ]);
      setDevices(deviceRows);
      setChannels(channelRows);
    } catch (err) {
      addToast(failureText(err, "Could not load notification settings"), "error");
    }
  }, [addToast]);

  useEffect(() => {
    void refresh();
    if (!pushSupported) return;
    let cancelled = false;
    navigator.serviceWorker.ready
      .then((registration) => registration.pushManager.getSubscription())
      .then((subscription) => { if (!cancelled) setThisDevice(subscription); })
      .catch(() => { if (!cancelled) setThisDevice(null); });
    return () => { cancelled = true; };
  }, [pushSupported, refresh]);

  const enablePush = async () => {
    setBusy(true);
    try {
      const answer = await Notification.requestPermission();
      setPermission(answer);
      if (answer !== "granted") {
        addToast("Notifications stay off until your browser allows them.", "warning");
        return;
      }
      const publicKey = await notificationService.vapidPublicKey();
      const registration = await navigator.serviceWorker.ready;
      const subscription =
        (await registration.pushManager.getSubscription()) ??
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(publicKey),
        }));
      const json = subscription.toJSON();
      if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
        throw new Error("The browser returned an incomplete push subscription");
      }
      await notificationService.subscribePush({
        endpoint: json.endpoint,
        keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      });
      setThisDevice(subscription);
      addToast("Push notifications are on for this device.", "success");
      await refresh();
    } catch (err) {
      addToast(failureText(err, "Could not turn on push notifications"), "error");
    } finally {
      setBusy(false);
    }
  };

  const disablePush = async () => {
    if (!thisDevice) return;
    setBusy(true);
    try {
      const endpoint = thisDevice.endpoint;
      await thisDevice.unsubscribe();
      await notificationService.unsubscribePush(endpoint);
      setThisDevice(null);
      addToast("Push notifications are off for this device.", "success");
      await refresh();
    } catch (err) {
      addToast(failureText(err, "Could not turn off push notifications"), "error");
    } finally {
      setBusy(false);
    }
  };

  const removeDevice = async (device: PushDevice) => {
    try {
      await notificationService.removeDevice(device.id);
      await refresh();
    } catch (err) {
      addToast(failureText(err, "Could not remove the device"), "error");
    }
  };

  const addChannel = async (event: React.FormEvent) => {
    event.preventDefault();
    const url = channelUrl.trim();
    if (!url) return;
    setBusy(true);
    try {
      await notificationService.addChannel({ url, label: channelLabel.trim() });
      setChannelUrl("");
      setChannelLabel("");
      addToast("Notification URL saved. Send a test to check it.", "success");
      await refresh();
    } catch (err) {
      addToast(failureText(err, "Could not save that notification URL"), "error");
    } finally {
      setBusy(false);
    }
  };

  const toggleChannel = async (channel: NotificationChannel) => {
    try {
      await notificationService.updateChannel(channel.id, { enabled: !channel.enabled });
      await refresh();
    } catch (err) {
      addToast(failureText(err, "Could not change that notification URL"), "error");
    }
  };

  const removeChannel = async (channel: NotificationChannel) => {
    try {
      await notificationService.removeChannel(channel.id);
      await refresh();
    } catch (err) {
      addToast(failureText(err, "Could not remove that notification URL"), "error");
    }
  };

  const sendTest = async () => {
    setBusy(true);
    try {
      setTestResult(await notificationService.sendTest());
      await refresh();
    } catch (err) {
      addToast(failureText(err, "The test could not be sent"), "error");
    } finally {
      setBusy(false);
    }
  };

  const hasTargets = channels.some((channel) => channel.enabled) || devices.length > 0;

  return (
    <div className="notification-settings">
      <article className="integrations-panel">
        <header>
          <div>
            <h2>This device</h2>
            <p>
              Browser push shows updates on this device, even when Nexus is closed. On iPhone and iPad, add
              Nexus to your Home Screen first.
            </p>
          </div>
          <span>{thisDevice ? "On" : "Off"}</span>
        </header>
        {permission === "unsupported" && (
          <p className="integrations-muted">This browser does not support push notifications.</p>
        )}
        {permission === "denied" && (
          <p className="integrations-muted">
            Notifications are blocked for this site. Allow them in your browser's site settings, then try again.
          </p>
        )}
        {pushSupported && permission !== "denied" && (
          <div className="integration-form">
            {thisDevice ? (
              <button type="button" className="operations-action operations-action--quiet" disabled={busy} onClick={() => void disablePush()}>
                Turn off on this device
              </button>
            ) : (
              <button type="button" className="operations-action" disabled={busy} onClick={() => void enablePush()}>
                <BellRing size={14} aria-hidden="true" /> Turn on push notifications
              </button>
            )}
          </div>
        )}
        {devices.length > 0 && (
          <div className="integrations-list" aria-label="Devices with push notifications">
            {devices.map((device) => (
              <div className="integration-row" key={device.id}>
                <div>
                  <strong>{device.user_agent || "Unknown device"}</strong>
                  <small>
                    Last delivered: {formatTime(device.last_success_at)}
                    {device.failure_count > 0 && ` · ${device.failure_count} failed attempt(s)`}
                  </small>
                </div>
                <div className="integration-actions">
                  <button type="button" className="operations-action operations-action--quiet" onClick={() => void removeDevice(device)}>
                    <Trash2 size={14} aria-hidden="true" /> Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </article>

      <article className="integrations-panel">
        <header>
          <div>
            <h2>Other apps and services</h2>
            <p>
              Send updates to ntfy, e-mail, Telegram, Discord and more through an Apprise URL. Nexus stores the
              URL encrypted and only shows its scheme and host.{" "}
              <a href={APPRISE_HELP_URL} target="_blank" rel="noreferrer">How to write Apprise URLs</a>
            </p>
          </div>
        </header>
        <form className="integration-form" onSubmit={addChannel}>
          <label>
            Label (optional)
            <input value={channelLabel} onChange={(event) => setChannelLabel(event.target.value)} maxLength={120} placeholder="Phone via ntfy" autoComplete="off" />
          </label>
          <label>
            Apprise URL
            <input
              value={channelUrl}
              onChange={(event) => setChannelUrl(event.target.value)}
              placeholder="ntfy://your-topic"
              autoComplete="off"
              spellCheck={false}
              autoCapitalize="off"
              required
            />
          </label>
          <button className="operations-action" disabled={busy || !channelUrl.trim()}>Save URL</button>
        </form>
        {channels.length > 0 && (
          <div className="integrations-list">
            {channels.map((channel) => (
              <div className="integration-row" key={channel.id}>
                <div>
                  <strong>{channel.label || channel.url_hint}</strong>
                  <small>
                    {channel.url_hint}
                    {channel.last_error && <span className="integration-warning"> · Last send failed: {channel.last_error}</span>}
                  </small>
                </div>
                <div className="integration-actions">
                  <label>
                    <input type="checkbox" checked={channel.enabled} onChange={() => void toggleChannel(channel)} aria-label={`Enabled: ${channel.label || channel.url_hint}`} />{" "}
                    {channel.enabled ? "On" : "Off"}
                  </label>
                  <button type="button" className="operations-action operations-action--quiet" onClick={() => void removeChannel(channel)}>
                    <Trash2 size={14} aria-hidden="true" /> Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </article>

      <article className="integrations-panel">
        <header>
          <div>
            <h2>Send a test</h2>
            <p>Sends one message to every enabled URL and every device above.</p>
          </div>
        </header>
        <div className="integration-form">
          <button type="button" className="operations-action" disabled={busy || !hasTargets} onClick={() => void sendTest()}>
            <Send size={14} aria-hidden="true" /> Send test
          </button>
        </div>
        {testResult && (
          <ul className="notification-test-results" aria-label="Test results">
            {testResult.channels.map((result) => (
              <li key={result.id}>
                {result.label || result.url_hint}: {result.ok ? "sent" : `failed (${result.error})`}
              </li>
            ))}
            {testResult.push.sent + testResult.push.failed + testResult.push.removed > 0 && (
              <li>
                Devices: {testResult.push.sent} sent, {testResult.push.failed} failed, {testResult.push.removed} removed
              </li>
            )}
          </ul>
        )}
      </article>
    </div>
  );
};

export default NotificationSettings;
