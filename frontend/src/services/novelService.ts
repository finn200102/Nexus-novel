import apiClient from "./apiClient";
import axios from "axios";

interface CreateNovelSchema {
  url: string;
  library_id: number;
}
interface GetNovelSchema {
  library_id: number;
  novel_id: number;
}

export const novelService = {
  async getAllNovels(library_id: number) {
    try {
      const response = await apiClient.get(`/novel/?library_id=${library_id}`);
      return response.data;
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

  handleError(error: any, message: string) {
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
