import apiClient from "./apiClient";

export type PushDevice = {
  id: number;
  user_agent: string | null;
  created_at: string | null;
  last_success_at: string | null;
  failure_count: number;
};

export type NotificationChannel = {
  id: number;
  kind: string;
  label: string;
  /** Scheme and host only; the full Apprise URL is never sent back. */
  url_hint: string;
  enabled: boolean;
  last_error: string | null;
  created_at: string | null;
};

export type PushSubscriptionInput = {
  endpoint: string;
  keys: { p256dh: string; auth: string };
};

export type ChannelTestResult = {
  channels: { id: number; label: string; url_hint: string; ok: boolean; error: string | null }[];
  push: { sent: number; failed: number; removed: number };
};

export const notificationService = {
  vapidPublicKey: async () =>
    (await apiClient.get<{ public_key: string }>("/notifications/vapid-public-key")).data.public_key,
  devices: async () => (await apiClient.get<PushDevice[]>("/notifications/push/subscriptions")).data,
  subscribePush: async (subscription: PushSubscriptionInput) =>
    (await apiClient.post<PushDevice>("/notifications/push/subscriptions", subscription)).data,
  unsubscribePush: async (endpoint: string) => {
    await apiClient.post("/notifications/push/unsubscribe", { endpoint });
  },
  removeDevice: async (id: number) => {
    await apiClient.delete(`/notifications/push/subscriptions/${id}`);
  },
  channels: async () => (await apiClient.get<NotificationChannel[]>("/notifications/channels")).data,
  addChannel: async (channel: { url: string; label: string }) =>
    (await apiClient.post<NotificationChannel>("/notifications/channels", channel)).data,
  updateChannel: async (id: number, changes: { enabled?: boolean; label?: string }) =>
    (await apiClient.patch<NotificationChannel>(`/notifications/channels/${id}`, changes)).data,
  removeChannel: async (id: number) => {
    await apiClient.delete(`/notifications/channels/${id}`);
  },
  sendTest: async () => (await apiClient.post<ChannelTestResult>("/notifications/test")).data,
};
