import apiClient from "./apiClient";
import { DiscoveryFilters } from "../types/discovery";

export type SavedSearch = {
  id: number;
  name: string;
  filters: Partial<DiscoveryFilters>;
  notify_on_match: boolean;
};

export const savedSearchService = {
  async list(): Promise<SavedSearch[]> {
    return (await apiClient.get("/saved-searches")).data;
  },
  async create(name: string, filters: DiscoveryFilters, notifyOnMatch = false): Promise<SavedSearch> {
    return (await apiClient.post("/saved-searches", {
      name,
      filters,
      notify_on_match: notifyOnMatch,
    })).data;
  },
  async remove(id: number) {
    await apiClient.delete(`/saved-searches/${id}`);
  },
};
