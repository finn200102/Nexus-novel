import apiClient from "./apiClient";

export type MergeReview = {
  id: number;
  target_novel_id: number;
  target_title: string;
  status: string;
  confidence: number;
  match_reasons: string[];
  conflicts: string[];
  source: { site: string; canonical_url: string; novel_id: number };
};

export type WebhookSubscription = {
  id: string;
  name: string;
  target_url: string;
  event_types: string[];
  enabled: boolean;
  failure_count: number;
  last_error?: string | null;
  last_delivered_at?: string | null;
};

export type WebhookDelivery = {
  id: string;
  event_type: string;
  status: string;
  attempt_count: number;
  next_attempt_at?: string | null;
  delivered_at?: string | null;
  last_error?: string | null;
};

export const adminIntegrationService = {
  async mergeReviews() { return (await apiClient.get("/admin/integrations/merge-reviews")).data.data as MergeReview[]; },
  async decideMerge(id: number, action: "approve" | "reject" | "revert", note?: string) {
    return (await apiClient.post(`/admin/integrations/merge-reviews/${id}/${action}`, { note: note || null })).data;
  },
  async webhooks() { return (await apiClient.get("/admin/integrations/webhooks")).data as WebhookSubscription[]; },
  async createWebhook(input: { name: string; target_url: string; secret: string; event_types: string[]; enabled: boolean }) {
    return (await apiClient.post("/admin/integrations/webhooks", input)).data as WebhookSubscription;
  },
  async deleteWebhook(id: string) { await apiClient.delete(`/admin/integrations/webhooks/${id}`); },
  async testWebhook(id: string) { return (await apiClient.post(`/admin/integrations/webhooks/${id}/test`)).data as { queued: boolean; event_id: string }; },
  async rotateSecret(id: string, secret: string) { return (await apiClient.post(`/admin/integrations/webhooks/${id}/rotate-secret`, { secret })).data as WebhookSubscription; },
  async webhookHistory(id: string) { return (await apiClient.get(`/admin/integrations/webhooks/${id}/history`)).data.data as WebhookDelivery[]; },
};
