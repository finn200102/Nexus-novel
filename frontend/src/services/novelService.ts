import apiClient from "./apiClient";
import axios from "axios";

interface CreateNovelSchema {
  url: string;
  library_id: number;
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
