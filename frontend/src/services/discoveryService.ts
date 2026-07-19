import apiClient from "./apiClient";
import axios from "axios";
import { DiscoveredNovel, PaginatedResponse, SiteInfo } from "../types/discovery";

export const discoveryService = {
  async getNovelsBySite(
    site: string | null,
    limit: number = 20,
    cursor: number | null = null,
    title: string | null = null
  ): Promise<PaginatedResponse<DiscoveredNovel>> {
    try {
      const params: Record<string, string | number | null> = {
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

      const response = await apiClient.get<PaginatedResponse<DiscoveredNovel>>(
        "/discovery/novels/",
        { params }
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
