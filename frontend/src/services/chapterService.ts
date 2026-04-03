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

  async resetChapterStatus(chapterId: number, status: string) {
    try {
      const response = await apiClient.patch(
        `/chapter/${chapterId}/status?content_status=${status}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error resetting chapter status");
      }
      throw error;
    }
  },

  async getDownloadStatus(novelId: number) {
    try {
      const response = await apiClient.get(`/chapter/novel/${novelId}/download-status`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching download status");
      }
      throw error;
    }
  },

  async cancelChapterDownload(chapterId: number) {
    try {
      const response = await apiClient.delete(`/chapter/${chapterId}/download`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error cancelling chapter download");
      }
      throw error;
    }
  },

  async cancelAllDownloads(novelId: number) {
    try {
      const response = await apiClient.post(`/chapter/novel/${novelId}/cancel-all-downloads`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error cancelling all downloads");
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
