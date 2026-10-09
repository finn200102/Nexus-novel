import apiClient from "./apiClient";

export type WebhookItem = {
  id: number;
  url_hint: string;
  has_secret: boolean;
  event_types: string[];
  enabled: boolean;
  last_status_code: number | null;
  last_error: string | null;
  last_delivered_at: string | null;
  consecutive_failures: number;
  created_at: string | null;
};

export type WebhookInput = {
  url: string;
  secret?: string;
  event_types?: string[];
  enabled?: boolean;
};

export type WebhookTestResult = {
  ok: boolean;
  status_code: number | null;
  error: string | null;
};

export type PersonalFeedStatus = {
  active: boolean;
  feed_url: string | null;
};

export const WEBHOOK_EVENT_LABELS: Record<string, string> = {
  new_chapters: "New chapters",
  source_failed: "Source failed",
  resumed: "Resumed",
};

export const feedWebhookService = {
  feedStatus: async () => (await apiClient.get<PersonalFeedStatus>("/personal-feed")).data,
  /** Creates the feed token, or rotates it. The returned URL is shown once. */
  rotateFeedToken: async () => (await apiClient.post<PersonalFeedStatus>("/personal-feed/token")).data,
  revokeFeedToken: async () => {
    await apiClient.delete("/personal-feed/token");
  },
  listWebhooks: async () => (await apiClient.get<WebhookItem[]>("/webhooks")).data,
  createWebhook: async (input: WebhookInput) => (await apiClient.post<WebhookItem>("/webhooks", input)).data,
  deleteWebhook: async (id: number) => {
    await apiClient.delete(`/webhooks/${id}`);
  },
  testWebhook: async (id: number) => (await apiClient.post<WebhookTestResult>(`/webhooks/${id}/test`)).data,
};
