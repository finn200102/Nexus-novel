import apiClient from "./apiClient";
import axios from "axios";
import type { Novel, NovelFollowSettings, NovelUpdateEvent } from "../types/novel";

interface CreateNovelSchema {
  url: string;
  library_id: number;
}
interface GetNovelSchema {
  library_id: number;
  novel_id: number;
}

export const novelService = {
  async getAllNovels(library_id: number, query: string = ""): Promise<Novel[]> {
    try {
      const response = await apiClient.get(`/novel/?library_id=${library_id}&search=${query}`);
      return response.data as Novel[];
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error fetching libraries");
      }
      throw error;
    }
  },
  async addNovel(library_id: number, url: string) {
    try {
      const data: CreateNovelSchema = {
        url: url,
        library_id: library_id,
      };
      const response = await apiClient.post(`/novel/`, data);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error fetching libraries");
      }
      throw error;
    }
  },
  async addNovels(libraryId: number, urls: string[]) {
    try {
      const downloadPromises = urls.map((url) => this.addNovel(libraryId, url));

      return await Promise.all(downloadPromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error download novels");
      }
      throw error;
    }
  },
  async getNovelById(library_id: number, novel_id: number) {
    try {
      const data: GetNovelSchema = {
        library_id: library_id,
        novel_id: novel_id,
      };

      const response = await apiClient.get(
        `/novel/${data.novel_id}?library_id=${data.library_id}`
      );

      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error fetching libraries");
      }
      throw error;
    }
  },
  async updateNovelChapters(library_id: number, novel_id: number) {
    try {
      const data = {
        library_id: library_id,
        novel_id: novel_id,
      };

      const response = await apiClient.get(
        `/novel/update/chapters/${data.novel_id}?library_id=${data.library_id}`
      );

      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error updating novel chapters");
      }
      throw error;
    }
  },
  async refreshMetadata(library_id: number, novel_id: number) {
    try {
      const response = await apiClient.get(
        `/novel/refresh/${novel_id}?library_id=${library_id}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error refreshing metadata");
      }
      throw error;
    }
  },
  async rescrapeNovel(library_id: number, novel_id: number) {
    try {
      const response = await apiClient.put(
        `/novel/${novel_id}?library_id=${library_id}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error rescrapping novel");
      }
      throw error;
    }
  },
  async deleteNovel(library_id: number, novel_id: number) {
    try {
      const data = {
        library_id: library_id,
        novel_id: novel_id,
      };

      const response = await apiClient.post(
        `/novel/delete/${data.novel_id}?library_id=${data.library_id}`
      );

      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status != 401) {
        this.handleError(error, "Error deleting novel");
      }
      throw error;
    }
  },
  async updateFollowState(
    libraryId: number,
    novelId: number,
    followState: "plan_to_read" | "reading" | "on_hold" | "completed" | "dropped" | "ignored",
    settings: Partial<NovelFollowSettings> = {},
  ): Promise<Novel> {
    const response = await apiClient.patch(
      `/novel/${novelId}/follow?library_id=${libraryId}`,
      {
        follow_state: followState,
        ...settings,
      }
    );
    return response.data as Novel;
  },
  async getFollowSettings(libraryId: number, novelId: number): Promise<NovelFollowSettings> {
    const response = await apiClient.get(`/novel/${novelId}/follow?library_id=${libraryId}`);
    return response.data as NovelFollowSettings;
  },
  async getUpdateEvents(libraryId: number, unreadOnly = false): Promise<NovelUpdateEvent[]> {
    const response = await apiClient.get(
      `/novel/updates?library_id=${libraryId}&unread_only=${unreadOnly}`
    );
    return response.data as NovelUpdateEvent[];
  },
  async markUpdateEventRead(eventId: number): Promise<NovelUpdateEvent> {
    const response = await apiClient.post(`/novel/updates/${eventId}/read`);
    return response.data as NovelUpdateEvent;
  },
  async deleteNovelsByIds(libraryId: number, novelIds: number[]) {
    try {
      const deletePromises = novelIds.map((novelId) =>
        this.deleteNovel(libraryId, novelId)
      );

      return await Promise.all(deletePromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error delete novels");
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
