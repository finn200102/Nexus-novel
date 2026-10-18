import apiClient from "./apiClient";

import type { EditionMember, EditionGroupResponse, EditionReviewView, EditionReviewSummary as ReviewSummary, EditionActionInput, EditionReviewResult, EditionReviewPage } from "../generated/api";
export type ReviewedEdition = EditionMember;
export type ReviewedEditionGroup = EditionGroupResponse;
export type EditionReview = EditionReviewView;
export type EditionReviewSummary = ReviewSummary;
export type ReviewPage<T> = Omit<EditionReviewPage, "items"> & { items: T[] };
export type EditionReviewAction = EditionActionInput;
export const editionReviewService = {
  group: async (novelId: number, signal?: AbortSignal): Promise<ReviewedEditionGroup> => (await apiClient.get(`/discovery/edition-groups/${novelId}`, { signal })).data,
  list: async (offset = 0, limit = 20): Promise<ReviewPage<EditionReviewSummary>> => (await apiClient.get("/admin/edition-group-reviews", { params: { offset, limit } })).data,
  get: async (id: string): Promise<EditionReview> => (await apiClient.get(`/admin/edition-group-reviews/${encodeURIComponent(id)}`)).data,
  preview: async (sourceNovelId: number, targetNovelId: number): Promise<EditionReview> => (await apiClient.post("/admin/edition-group-reviews/preview", { source_novel_id: sourceNovelId, target_novel_id: targetNovelId })).data,
  decide: async (id: string, action: "apply" | "undo", input: EditionReviewAction): Promise<EditionReviewResult> => (await apiClient.post(`/admin/edition-group-reviews/${encodeURIComponent(id)}/${action}`, input)).data,
};
