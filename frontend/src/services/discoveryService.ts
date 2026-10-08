import apiClient from "./apiClient";
import axios from "axios";
import {
  DiscoveredNovel,
  DiscoveryFilters,
  PaginatedResponse,
  SiteInfo,
  FandomInfo,
} from "../types/discovery";
import { discoveryFilterParams } from "./discoveryFilters";

export const discoveryService = {
  async getNovelsBySite(
    site: string | null,
    limit: number = 20,
    cursor: number | null = null,
    title: string | null = null,
    filters?: Partial<DiscoveryFilters>,
    similarTo?: number | null,
  ): Promise<PaginatedResponse<DiscoveredNovel>> {
    try {
      const params: Record<string, string | number | string[] | null> = {
        limit,
      };
      if (site && site !== "all") {
        params.site = site;
      }
      if (cursor) {
        params.cursor = cursor;
      }
      if (title?.trim()) {
        params.title = title.trim();
      }
      if (similarTo) {
        params.similar_to = similarTo;
      }
      Object.assign(params, discoveryFilterParams(filters ?? {}));

      // Axios would send arrays as tag[]=a; FastAPI expects repeated tag=a&tag=b.
      const response = await apiClient.get<PaginatedResponse<DiscoveredNovel>>(
        "/discovery/novels/",
        { params, paramsSerializer: { indexes: null } }
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching novels");
      }
      throw error;
    }
  },

  async getNovelById(novelId: number): Promise<DiscoveredNovel> {
    try {
      const response = await apiClient.get<DiscoveredNovel>(
        `/discovery/novels/${novelId}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching novel details");
      }
      throw error;
    }
  },

  async getSupportedSites(): Promise<SiteInfo[]> {
    try {
      const response = await apiClient.get<{ sites: SiteInfo[] }>("/discovery/sites/");
      return response.data.sites;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching sites");
      }
      throw error;
    }
  },

  async getFandoms(site?: string, query?: string): Promise<FandomInfo[]> {
    const response = await apiClient.get<FandomInfo[]>("/discovery/fandoms/", {
      params: { site: site && site !== "all" ? site : undefined, q: query || undefined, limit: 100 },
    });
    return response.data;
  },

  async addToLibrary(libraryId: number, sourceUrl: string): Promise<unknown> {
    try {
      const response = await apiClient.post(`/novel/`, {
        url: sourceUrl,
        library_id: libraryId,
      });
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error adding novel to library");
      }
      throw error;
    }
  },

  handleError(error: unknown, message: string) {
    console.error(message + ":", error);

    if (axios.isAxiosError(error)) {
      console.error("Response status:", error.response?.status);
      console.error("Response data:", error.response?.data);
      console.error("Request URL:", error.config?.url);
      console.error("Request method:", error.config?.method);
      console.error("Request headers:", error.config?.headers);
    }
  },
};
