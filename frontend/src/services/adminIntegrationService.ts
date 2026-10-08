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

export type GuideReviewAssertion = {
  id: string;
  subject?: string | null;
  predicate?: string | null;
  object?: string | null;
  chapter?: number | null;
  state?: string | null;
  review_state: "machine_suggested" | "approved" | "hidden" | "superseded";
  confidence?: number | null;
  qualifiers?: Record<string, string>;
  citations: Array<{ chapter: number; quote: string; start_offset?: number; end_offset?: number; anchor_state?: string }>;
  available_actions?: string[];
};

export type GuideReviewHistoryItem = {
  id: string;
  assertion_id: string;
  action: string;
  from_state?: string | null;
  to_state?: string | null;
  reason?: string | null;
  created_at?: string | null;
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
  async storyGuideReviewQueue(novelId: number) {
    return (await apiClient.get(`/admin/integrations/story-guides/${novelId}/review-queue`)).data as { data?: GuideReviewAssertion[]; assertions?: GuideReviewAssertion[] };
  },
  async storyGuideReviewHistory(novelId: number) {
    return (await apiClient.get(`/admin/integrations/story-guides/${novelId}/review-history`)).data as { data?: GuideReviewHistoryItem[]; history?: GuideReviewHistoryItem[] };
  },
  async reviewStoryGuideAssertion(assertionId: string, review_state: "machine_suggested" | "approved" | "hidden", reason?: string) {
    return (await apiClient.post(`/admin/integrations/story-guides/assertions/${assertionId}/review`, { review_state, reason: reason || null })).data;
  },
  async restoreStoryGuideAssertion(assertionId: string, reason?: string) {
    return (await apiClient.post(`/admin/integrations/story-guides/assertions/${assertionId}/restore`, { reason: reason || null })).data;
  },
};
