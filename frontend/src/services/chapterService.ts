import apiClient from "./apiClient";
import axios from "axios";

export const chapterService = {
  async getChapters(novelId: number) {
    try {
      const response = await apiClient.get(`/chapter/${novelId}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapter(novelId: number, chapterNumber: number) {
    try {
      const response = await apiClient.get(
        `/chapter/download/${novelId}/${chapterNumber}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapters(novelId: number, chapterNumbers: number[]) {
    try {
      const downloadPromises = chapterNumbers.map((chapterNumber) =>
        this.downloadChapter(novelId, chapterNumber)
      );

      return await Promise.all(downloadPromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error downloading chapters");
      }
      throw error;
    }
  },

  async getChapterContentByNumber(
    chapterNumber: number,
    libraryId: number,
    novelId: number
  ) {
    try {
      const response = await apiClient.get(
        `/chapter/content/library/${libraryId}/${novelId}/${chapterNumber}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
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
