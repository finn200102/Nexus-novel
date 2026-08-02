import apiClient from "./apiClient";

export type InsightSignal = { family: string; value: string; confidence?: number; evidence: Record<string, unknown>; model_version: string };
export type SimilarNovel = { novel_id: number; title: string; author?: string; score: number; explanation: string };
export type CanonicalWork = { id: number; title: string; editions: Array<{ id: number; novel_id: number; edition_kind: string; language?: string | null }> };

export const insightService = {
  async analysis(metadataId: number): Promise<{ signals: InsightSignal[] }> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/analysis`)).data;
  },
  async similar(metadataId: number): Promise<{ results: SimilarNovel[] }> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/similar`)).data;
  },
  async editions(metadataId: number): Promise<CanonicalWork> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/editions`)).data;
  },
};
