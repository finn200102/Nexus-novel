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
  async downloadChapter(
    library_id: number,
    novelId: number,
    chapterNumber: number
  ) {
    try {
      const response = await apiClient.get(
        `/chapter/download/${library_id}/${novelId}/${chapterNumber}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapters(
    library_id: number,
    novelId: number,
    chapterNumbers: number[]
  ) {
    try {
      const downloadPromises = chapterNumbers.map((chapterNumber) =>
        this.downloadChapter(library_id, novelId, chapterNumber)
      );

      return await Promise.all(downloadPromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error downloading chapters");
      }
      throw error;
    }
  },

  async createAudioChapter(
    library_id: number,
    novelId: number,
    chapterNumber: number
  ) {
    try {
      const response = await apiClient.get(
        `/chapter/audio/${library_id}/${novelId}/${chapterNumber}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async createAudioChapters(
    library_id: number,
    novelId: number,
    chapterNumbers: number[]
  ) {
    try {
      const downloadPromises = chapterNumbers.map((chapterNumber) =>
        this.createAudioChapter(library_id, novelId, chapterNumber)
      );

      return await Promise.all(downloadPromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error creating audio chapters");
      }
      throw error;
    }
  },

  async getChapterAudio(
    libraryId: number,
    novelId: number,
    chapterNumber: number
  ): Promise<string> {
    const { data } = await apiClient.get(
      `/chapter/content/library/${libraryId}/${novelId}/${chapterNumber}/audio`,
      { responseType: "blob" } // ↙ returns binary data
    );

    // Turn the Blob into an object‑URL the browser can play
    return URL.createObjectURL(new Blob([data], { type: "audio/mpeg" }));
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

  async deleteChapterById(chapterId: number) {
    try {
      const response = await apiClient.delete(`/chapter/${chapterId}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error deleting chapter");
      }
      throw error;
    }
  },
  async deleteChaptersByIds(chapterIds: number[]) {
    try {
      const deletePromises = chapterIds.map((chapterId) =>
        this.deleteChapterById(chapterId)
      );

      return await Promise.all(deletePromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error delete chapters");
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
