import React, { useEffect, useState } from "react";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";
import {
  PersonalFeedStatus,
  WEBHOOK_EVENT_LABELS,
  WebhookItem,
  feedWebhookService,
} from "../../services/feedWebhookService";
import "../../styles/integrations.css";

const EVENT_TYPES = Object.keys(WEBHOOK_EVENT_LABELS);

export const FeedsAndWebhooks: React.FC = () => {
  const { addToast } = useToast();
  const [feed, setFeed] = useState<PersonalFeedStatus | null>(null);
  const [feedUrl, setFeedUrl] = useState<string | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookItem[]>([]);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [events, setEvents] = useState<string[]>(["new_chapters"]);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [status, hooks] = await Promise.all([feedWebhookService.feedStatus(), feedWebhookService.listWebhooks()]);
      setFeed(status);
      setWebhooks(hooks);
    } catch (err) {
      addToast(getUserFacingError(err, "Could not load feeds and webhooks"), "error");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rotate = async () => {
    setBusy(true);
    try {
      const created = await feedWebhookService.rotateFeedToken();
      setFeed(created);
      setFeedUrl(created.feed_url);
      addToast("New feed URL created. The old one no longer works.", "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not create the feed URL"), "error");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    setBusy(true);
    try {
      await feedWebhookService.revokeFeedToken();
      setFeed({ active: false, feed_url: null });
      setFeedUrl(null);
      addToast("Feed URL revoked", "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not revoke the feed URL"), "error");
    } finally {
      setBusy(false);
    }
  };

  const copyFeed = async () => {
    if (!feedUrl) return;
    try {
      await navigator.clipboard.writeText(feedUrl);
      addToast("Feed URL copied", "success");
    } catch {
      addToast("Could not copy. Select the URL and copy it by hand.", "error");
    }
  };

  const toggleEvent = (type: string) =>
    setEvents((current) => (current.includes(type) ? current.filter((t) => t !== type) : [...current, type]));

  const addWebhook = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!url.trim() || events.length === 0) return;
    setBusy(true);
    try {
      const created = await feedWebhookService.createWebhook({
        url: url.trim(),
        secret: secret || undefined,
        event_types: events,
      });
      setWebhooks((current) => [...current, created]);
      setUrl("");
      setSecret("");
      addToast("Webhook added", "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not add the webhook"), "error");
    } finally {
      setBusy(false);
    }
  };

  const test = async (hook: WebhookItem) => {
    try {
      const result = await feedWebhookService.testWebhook(hook.id);
      addToast(result.ok ? "Test delivered" : `Test failed: ${result.error ?? "unknown error"}`, result.ok ? "success" : "error");
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Test failed"), "error");
    }
  };

  const remove = async (hook: WebhookItem) => {
    try {
      await feedWebhookService.deleteWebhook(hook.id);
      setWebhooks((current) => current.filter((item) => item.id !== hook.id));
    } catch (err) {
      addToast(getUserFacingError(err, "Could not delete the webhook"), "error");
    }
  };

  return (
    <article className="integrations-panel">
      <header>
        <div>
          <h2>Feeds and webhooks</h2>
          <p>Follow updates in a feed reader, or have Nexus post each update to your own server.</p>
        </div>
      </header>

      <section aria-labelledby="personal-feed-heading">
        <h3 id="personal-feed-heading">Personal feed</h3>
        <p>
          {feed?.active
            ? "A feed URL is active. Its secret is only shown when you create or rotate it, so copy it now."
            : "No feed URL yet. Create one to read your updates in a feed reader."}
        </p>
        {feedUrl && (
          <div className="account-form">
            <input readOnly aria-label="Feed URL" value={feedUrl} onFocus={(e) => e.currentTarget.select()} />
            <button type="button" onClick={copyFeed}>Copy feed URL</button>
          </div>
        )}
        <div className="account-form">
          <button type="button" onClick={rotate} disabled={busy}>
            {feed?.active ? "Rotate feed URL" : "Create feed URL"}
          </button>
          {feed?.active && (
            <button type="button" onClick={revoke} disabled={busy}>
              Revoke feed URL
            </button>
          )}
        </div>
      </section>

      <section aria-labelledby="webhooks-heading">
        <h3 id="webhooks-heading">Webhooks</h3>
        {webhooks.length === 0 && <p>No webhooks yet.</p>}
        <ul>
          {webhooks.map((hook) => (
            <li key={hook.id}>
              <strong>{hook.url_hint}</strong>{" "}
              <span>
                {hook.enabled ? "" : "(disabled) "}
                {hook.event_types.map((t) => WEBHOOK_EVENT_LABELS[t] ?? t).join(", ")}
                {hook.has_secret ? " · signed" : ""}
              </span>
              {hook.last_error && <div role="status">Last error: {hook.last_error}</div>}
              <div className="account-form">
                <button type="button" onClick={() => test(hook)}>Send test</button>
                <button type="button" onClick={() => remove(hook)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>

        <form className="account-form" onSubmit={addWebhook}>
          <label>
            Endpoint URL
            <input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hook" />
          </label>
          <label>
            Signing secret (optional)
            <input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
          </label>
          <fieldset>
            <legend>Events</legend>
            {EVENT_TYPES.map((type) => (
              <label key={type}>
                <input type="checkbox" checked={events.includes(type)} onChange={() => toggleEvent(type)} />{" "}
                {WEBHOOK_EVENT_LABELS[type]}
              </label>
            ))}
          </fieldset>
          <button type="submit" disabled={busy || !url.trim() || events.length === 0}>
            Add webhook
          </button>
        </form>
      </section>
    </article>
  );
};

export default FeedsAndWebhooks;
